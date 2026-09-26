#!/usr/bin/env python3
"""Structural facts about our clues, read off the blogs that explain them.

timesforthetimes, fifteensquared and bigdave44 write up most of the puzzles we
hold. Their prose is theirs and is never copied. What this keeps is what the
blogger's markup states about the clue itself:

  * the definition: the words the blogger underlined, which are words of the
    clue, so a span is kept only where it is an exact run of whole words of
    OUR copy of the clue;
  * the building blocks, where the write-up gives its wordplay as capitals
    and the clue words they come from: TAKE (arrange), NIC[k] (cut), PAPA =
    pop, scheme (PLOT). Kept as [letters, clue words], and only where the
    words are an exact run of whole words of our clue (see blocks);
  * the clue type, where the write-up names it in a form that means one thing
    (see TYPES) and, for an anagram, holds fodder with the answer's letters;
    or where its wordplay spells the type out, which is kept only when the
    pieces put together by its own operators give exactly the answer (see
    wordplay_type);
  * the indicators, only where a convention marks them: a bracketed [word]
    under a timesforthetimes key that says so, an italic (<em>word</em>), the
    gloss on a named operation ("<em>reversed</em> (backing)", "anagram
    (strangely) of"), and again only words that are in the clue.

The join never trusts a title. A post is a candidate for every puzzle whose
number its title carries, and it is that puzzle's post only if our clue texts
are found in it, in order: a clue is a long enough string that finding it is
the proof.

    python3 tools/blog_facts.py            # write tools/data/blog_facts/
    python3 tools/blog_facts.py --measure  # and print coverage per blog and series
    python3 tools/blog_facts.py --sample 30 --seed 1   # and print rows to check by hand
    python3 tools/blog_facts.py --if-changed  # the nightly: skip when no input moved
    python3 tools/blog_facts.py --jobs 1      # one process; the default pool takes ~2 GB
    python3 tools/blog_facts.py --score       # precision and recall against blog_facts_gold.jsonl

Reads the caches the fetchers write under ~/cryptic-setter-data; never the
network.
"""
import argparse
import ast
import collections
import hashlib
import html
import html.parser
import json
import os
import random
import re
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from fetch_puzzle import puzzle_files, read_puzzle_file

DATA = Path.home() / "cryptic-setter-data"
OUT = ROOT / "tools" / "data" / "blog_facts"
#: The digest of every input the files in OUT were written from; see inputs_digest.
STAMP = OUT / "inputs.sha256"

#: Blog key -> (cache directory, the name a reader is shown). The key is what
#: the sidecar stores; the name is what the site prints beside the link.
BLOGS = {
    "timesforthetimes": (DATA / "timesforthetimes", "Times for the Times"),
    "fifteensquared": (DATA / "fifteensquared", "Fifteensquared"),
    "bigdave44": (DATA / "bigdave44", "Big Dave's Crossword Blog"),
}

#: A post is a puzzle's write-up when at least this share of its clues is found
#: in it. Old Times posts blog only the interesting clues, so this is low; a
#: wrong puzzle scores zero, never a half.
MIN_ALIGNED = 0.3

U_ON, U_OFF, E_ON, E_OFF = "", "", "", ""
MARKS = U_ON + U_OFF + E_ON + E_OFF
BLOCK_TAGS = {"p", "br", "div", "tr", "td", "th", "li", "h1", "h2", "h3", "h4",
              "h5", "h6", "table", "tbody", "ul", "ol"}
UNDERLINE_STYLE = re.compile(r"text-decoration\s*:\s*underline", re.I)
SKIP_TAGS = {"s", "strike", "del", "script", "style"}


class _Flatten(html.parser.HTMLParser):
    """HTML to text, with underline and emphasis kept as sentinel characters."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        if tag in ("br", "img", "hr"):
            return
        mark = ""
        if tag in SKIP_TAGS:
            self.skip += 1
            mark = "skip"
        elif tag in ("u", "ins") or UNDERLINE_STYLE.search(dict(attrs).get("style") or ""):
            mark = U_ON
        elif tag in ("em", "i"):
            mark = E_ON
        if mark and mark != "skip":
            self.out.append(mark)
        self.stack.append((tag, mark))

    def handle_endtag(self, tag):
        if tag in BLOCK_TAGS:
            self.out.append("\n")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for _, mark in reversed(self.stack[i:]):
                    if mark == "skip":
                        self.skip -= 1
                    elif mark:
                        self.out.append(U_OFF if mark == U_ON else E_OFF)
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def flatten(rendered):
    p = _Flatten()
    p.feed(rendered)
    p.close()
    return "".join(p.out).replace("\xa0", " ")


def fold(ch):
    """A character as the letter it is compared by: accents off, lower case."""
    return unicodedata.normalize("NFKD", ch)[:1].lower()


def projection(text, marked=False):
    """(letters, positions, underline runs, emphasis flags) of a text.

    An underline run is numbered, 0 for none, so two underlines with only a
    space between them stay two spans: a double definition is two.

    Only letters are compared: punctuation, quotes, spacing and enumerations
    differ between a blog's copy of a clue and the paper's."""
    letters, pos, under, emph = [], [], [], []
    u = e = run = 0
    joined = False  # an underline resuming mid-word, as in Me<u>di</u>a, is the same span
    for i, ch in enumerate(text):
        if marked and ch in MARKS:
            if ch == U_ON and u == 0 and not joined:
                run += 1
            u += {U_ON: 1, U_OFF: -1}.get(ch, 0)
            e += {E_ON: 1, E_OFF: -1}.get(ch, 0)
            continue
        f = fold(ch)
        joined = bool(u) and f.isalnum() or (joined and ch in MARKS)
        if f.isalnum() and f.isascii():
            letters.append(f)
            pos.append(i)
            under.append(run if u > 0 else 0)
            emph.append(e > 0)
    return "".join(letters), pos, under, emph


ENUM_TAIL = re.compile(r"\s*\((?:[\d,\s\-–.]|words?)+\)\s*$")


def clue_body(clue):
    """The clue without its enumeration, which blogs print in varied forms."""
    return ENUM_TAIL.sub("", clue or "").strip()


def is_word_start(s, i):
    return i == 0 or not s[i - 1].isalnum()


def is_word_end(s, j):
    return j >= len(s) or not s[j].isalnum() or s[j] in "'’"


def spans_of(runs, pos, body):
    """Underline runs over the clue's letters, as whole-word substrings of
    `body`, or None when any run cuts into a word (a sloppy underline)."""
    out, i = [], 0
    while i < len(runs):
        if not runs[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(runs) and runs[j + 1] == runs[i]:
            j += 1
        a, b = pos[i], pos[j] + 1
        if not (is_word_start(body, a) and is_word_end(body, b)):
            return None
        out.append(body[a:b])
        i = j + 1
    return out


# --------------------------------------------------------------------- types

#: Where a sentence of a write-up begins: a clue type is named at the start
#: of one ("Hidden in ...", "BRUSSELS – hidden reversed ...").
OPENS = r"(?:^|(?<=[\n:–—;.(])|(?<=[\n:–—;.(] ))\s*(?:it's\s+|this\s+is\s+|an?\s+|just\s+an?\s+|simply\s+an?\s+)?"

#: The wordplay a write-up names in a form that means one thing, as the
#: TYPE_PARTS string app.js's familyOf reads. First match wins, in the same
#: dominance order as FAMILIES. &lit is not read: bloggers and annotators
#: split on &lit against cryptic definition too often for it to be a fact.
TYPES = (
    ("double definition", re.compile(
        r"\b(?:double|two|triple|three)[\s-]+def(?:inition|n)?s?\b|\bDD\b|\b2\s?defs?\b"
        r"|\b(?:two|three) meanings\b", re.I)),
    ("cryptic definition", re.compile(OPENS + r"(?:cryptic(?:ally)?\s+def(?:inition)?|CD)\b", re.I)),
    ("anagram", re.compile(r"\banagram\b|\banag\b|[A-Z)]\*|\*\s*\(|\banagrind", re.I)),
    ("spoonerism", re.compile(r"\bspooner(?:ism|'s)?\b", re.I)),
    ("homophone", re.compile(r"\bhomophone\b|\bsounds like\b", re.I)),
    ("hidden word", re.compile(
        OPENS + r"(?:reversed?\s+|reverse\s+)?hidden\b"
        r"|\bhidden\s+(?:reversed?\s+|backwards\s+)?(?:word\s+)?(?:in|within|inside)\b|\[hidden", re.I)),
)
#: A write-up that hedges ("almost a DD", "a dd cum cd", "sort of") or denies
#: ("not an anagram") has not named the type, so nothing is read off it.
HEDGED = re.compile(
    r"\bnot\s+(?:an?\s+|the\s+|quite\s+)?(?:anagram|homophone|hidden|double|cryptic|&\s*lit)"
    r"|\bnot quite\b|\balmost\b|\bsort of\b|\bkind of\b|\bnearly\b|\bish\b|\bcum\b"
    r"|\bI think\b|\bI suppose\b|\bdefinition\s*\?|\b[cd]d\s*\?"
    r"|\b[cd]d\s*/\s*[cd]d\b|\bsemi|\bor (?:an?|the) (?:anagram|homophone|double|cryptic|&\s*lit)",
    re.I)
REVERSED = re.compile(r"\brevers|\bbackwards?\b|\bup\b(?=.*\bhidden)", re.I)


def clue_type(expl):
    """The one clue type `expl` names unambiguously, or None."""
    if HEDGED.search(expl):
        return None
    for name, rx in TYPES:
        if rx.search(expl):
            if name == "hidden word" and REVERSED.search(expl):
                return "hidden word + reversal"
            return name
    return None


# ---------------------------------------------------------------- indicators

#: A timesforthetimes post puts indicators in [square brackets] only where its
#: blogger's key says so; other bloggers' brackets hold glosses or deletions.
BRACKETS_ARE_INDICATORS = re.compile(r"(?:indicators|directions) in square (?:ones|brackets)", re.I)
BRACKETED = re.compile(r"(?<![A-Za-z])\[([^\[\]]{2,60})\](?![A-Za-z])")
ITALIC_IN_PARENS = re.compile(r"\(" + E_ON + r"([^" + MARKS + r"()]{2,60})" + E_OFF + r"\)")
ELLIPSIS = re.compile(r"\s*(?:…|\.\.\.)\s*")


def in_clue(phrase, body):
    """`phrase` as an exact run of whole words of `body`, spelled as in body.
    Curly and straight apostrophes are one character here."""
    phrase = phrase.strip(" '‘’\"“”,.;:!?")
    if len(phrase) < 2:
        return None
    norm = lambda t: t.replace("’", "'").replace("‘", "'")
    m = re.search(r"(?<![\w'])" + re.escape(norm(phrase)) + r"(?![\w])", norm(body), re.I)
    return body[m.start():m.end()] if m else None


# ------------------------------------------------------------------ wordplay

#: A capital block as the blogs write it: capitals, maybe several words of
#: them, with deleted or expanded letters attached in brackets or lower-case
#: parentheses (UA[E], PLUT{o}, R(un), (fac)E). Only the capitals are letters.
CAP = "A-ZÀ-ÖØ-Þ"
ATT = r"(?:\[[A-Za-z]{1,15}\]|\{[A-Za-z]{1,15}\}|\([A-Za-z]{1,15}\))"
CAPWORD = rf"(?:{ATT})*[{CAP}](?:[{CAP}'’.\-]|{ATT})*(?<![’'.\-])(?:['’]s(?![a-z]))?"
ATOM = re.compile(rf"(?<![\w'’])(?:{CAPWORD})(?: (?:{CAPWORD}))*(?![\w\[{{])")
#: What a block's letters come from, right after them: `WORD (clue words)`,
#: `WORD(‘clue words’)`, `WORD (=clue words)`, `WORD [clue words]`,
#: `WORD=“clue words”`, `WORD = clue words` or `WORD for ‘clue words’`.
QUOTED = r"['‘\"“](?P<q>[^'‘’\"“”()]{1,60})['’\"”]"
SOURCE = re.compile(
    r"\s*\(\s*=?\s*(?:" + QUOTED.replace("q>", "p>") + r"|(?P<s>[^()]{1,150}))\s*\)"
    r"|\s*\[\s*(?P<b>[^\[\]]{1,60})\s*\]"
    r"|\s*=\s*(?:" + QUOTED + r"|(?P<e>[A-Za-z][a-z'’ \-]{0,40}))"
    r"|\s+for\s+" + QUOTED.replace("q>", "f>"))
#: A gloss that names its clue words among other things: "(staff, long piece
#: of wood)", "(publicity – Public Relations)".
GLOSS_PARTS = re.compile(r"\s*[,;]\s*|\s+[–—-]\s+")


def only_selecting(words):
    """Whether clue words say nothing but which letters to take ("topped and
    tailed"), which makes them the indicator of a cut and not a block's source
    unless the letters are in them ("most of the" -> TH)."""
    rest = SELECTING.sub(" ", words)
    return not re.sub(r"(?i)\b(?:and|of|the|a|an|its|at|to|in|on)\b|[^A-Za-z]", "", rest)


def source_words(m, body, no_brackets=False, multiword=False):
    """The clue words a SOURCE match names, as spelled in the clue, or None.
    A gloss naming them among other things is read only for a one-word block:
    "A PP (pianissimo, quiet)" does not say which letters are quiet."""
    if m.group("b") is not None and no_brackets:
        return None
    raw = next((m.group(g) for g in "psbqf" if m.group(g)), None)
    if raw:
        raw = raw.strip()
        if not re.search(r"[a-z]", raw):
            return None
        hit = in_clue(raw, body)
        if hit:
            return hit
        parts = [h for h in (in_clue(p, body) for p in GLOSS_PARTS.split(raw)) if h]
        return parts[0] if len(parts) == 1 and not multiword else None
    words = (m.group("e") or "").split()
    for k in range(min(4, len(words)), 0, -1):
        hit = in_clue(" ".join(words[:k]), body)
        if hit:
            return hit
    return None


def atom_letters(s):
    """The letters a capital block stands for: its capitals, folded."""
    s = re.sub(ATT, "", s)
    return "".join(f for f in map(fold, s) if f.isalnum() and f.isascii())


def whole_word_of(s):
    """R(un) -> Run, PLUT{o} -> PLUTo: the word an abbreviated block is cut
    from, or None when nothing is attached to it."""
    if not re.search(ATT, s) or " " in s:
        return None
    return re.sub(r"[\[\]{}()]", "", s)


#: A block written the other way round, clue words then letters: "scheme
#: (PLOT)". Only where the words run back to a clause boundary, so which words
#: they are is not a choice.
LETTERS_AFTER = re.compile(rf"(?:^|(?<=[,;:+()–—\n]))\s*(?P<w>[A-Za-z][a-z'’\-]*(?: [a-z][a-z'’\-]*){{0,2}})"
                           rf"\s*\((?P<l>[{CAP}][{CAP}'’ ]*)\)")


#: Clue words that put pieces together rather than give letters: a gloss
#: that holds one ("going round one area") is the blogger's reading of the
#: clue, not the words a block comes from.
OPERATES = re.compile(r"(?i)\b(?:going|goes|round|around|containing|holding|swallowing|embracing|"
                      r"reversed|returning|entering)\b")


ATTACHED = re.compile(rf"(?<![\w])([{CAP}][{CAP}'’]*)\(([{E_ON}]?)([a-z][a-z'’ \-]*)([{E_OFF}]?)\)")


def detach_sources(text, body):
    """HON(sweetheart) as HON (sweetheart): a source written against its
    letters, told from R(un), a word cut short, by which of the two is a word
    of the clue."""
    def one(m):
        caps, word = m.group(1), m.group(3)
        whole = (caps + word).lower()
        if whole in ABBR.get(atom_letters(caps), ()) or in_clue(caps + word, body) or not in_clue(word, body):
            return m.group()
        return f"{caps} ({m.group(2)}{word}{m.group(4)})"
    return ATTACHED.sub(one, text)


def blocks(expl, body, answer, bracket_key=False):
    """[(letters, clue words)] for every capital block the write-up sources
    to an exact run of whole words of the clue. A block that is the whole
    answer is the definition restated, not a piece of wordplay."""
    found = []
    for m in ATOM.finditer(expl):
        src = None
        s = SOURCE.match(expl, m.end())
        if s:
            # A bracket after a cut block glosses the cut; on a post whose key
            # puts indicators in brackets, no bracket is ever a source.
            src = source_words(s, body, bracket_key or bool(re.search(ATT, m.group())), " " in m.group())
            whole = whole_word_of(m.group())
            if src and whole and SELECTING.search(src) and in_clue(whole, body):
                src = None  # LAM(b) (‘tailless’): the gloss names the cut, and lamb is the word
            if src and not whole and only_selecting(src) and not selected(m.group(), src):
                src = None  # "final S (topped and tailed)": S is what goes, not a piece
        pieces = [m.group()]
        if not src and " " in m.group():
            # A(ny) E(nthusiasm): each word its own abbreviation; but
            # [slipsh]OD ESSA[y] is a hidden word, and its pieces no blocks.
            words = m.group().split(" ")
            hidden = re.match(ATT, words[0]) and re.search(rf"{ATT}$", words[-1])
            pieces = [] if hidden else words
        for n, piece in enumerate(pieces):
            whole = whole_word_of(piece)
            s2 = src or (in_clue(whole, body) if whole else None)
            if s2:
                found.append((m.start(), n, piece, s2))
    for m in LETTERS_AFTER.finditer(expl):
        src = in_clue(m.group("w"), body)
        if src:
            found.append((m.start(), 0, m.group("l"), src))
    out = []
    for _, _, piece, src in sorted(found):
        letters = atom_letters(piece)
        b = (re.sub(ATT, "", piece).strip(" .").upper(), src)
        if (letters and letters != answer and src.lower() != piece.lower() and b not in out
                and not (" " in src and OPERATES.search(src))):
            out.append(b)
    return out


# The operators a write-up spells its wordplay with, longest first within a
# kind. A binary one joins the pieces either side; `rev` operators take them
# in the other order ("POSERS after OP" is OP + POSERS).
OPS = {
    "concat": ["followed by", "plus", "and then", "and", "then", "+", "&", "before", "above",
               "on top of", "atop", "placed above", "placed before", "ahead of", "in front of"],
    "rconcat": ["preceded by", "coming after", "after", "following", "follows", "behind", "below",
                "beneath", "under", "underneath", "placed below", "placed under", "placed after",
                "comes after"],
    "adjoin": ["next to", "beside", "alongside", "with", "by", "against", "joined to", "joining",
               "attached to", "added to", "linked to", "together with"],
    "around": ["taking in", "takes in", "going round", "going around", "wrapped around",
               "around", "round", "containing", "contains", "holding", "holds", "outside",
               "covering", "swallowing", "embracing", "enclosing", "surrounding", "housing",
               "including", "includes", "grasping", "clutching", "eating", "about", "around",
               "annexes", "admits", "admitting", "accepts", "accepting", "grabs", "grabbing",
               "keeps", "keeping", "takes", "taking", "catches", "catching", "captures",
               "capturing", "hugs", "hugging", "clutches", "embraces", "swallows", "eats",
               "consumes", "consuming", "boxes", "boxing", "wraps", "wrapping", "covers",
               "surrounds", "encircles", "encircling", "circles", "circling", "envelops",
               "enveloping", "houses", "harbours", "harbouring", "has", "having", "gets in",
               "going outside", "goes around", "goes round", "to include", "includes",
               "sheltering", "shelters", "guarding", "guards", "nursing", "nurses", "hiding",
               "hides", "holding in", "keeping in", "taking up", "gripping", "grips", "outside of"],
    "inside": ["inserted into", "inserted in", "contained in", "contained by", "held by",
               "taken in by", "inside of", "going into", "put in", "inside", "within",
               "into", "entering", "in", "inserted", "put into", "interrupting", "interrupts",
               "splitting", "splits", "breaking", "breaks", "enters", "invading", "invades",
               "goes in", "going in", "caught by", "grabbed by", "held in", "swallowed by",
               "eaten by", "consumed by", "captured by", "kept by", "taken by", "boxed by",
               "wrapped in", "wrapped by", "covered by", "surrounded by", "embraced by",
               "hugged by", "clutched by", "gripped by", "housed by", "sheltered by", "nursed by",
               "inside of", "stuck in", "going inside", "put inside", "placed inside", "placed in"],
    "minus": ["removed from", "taken from", "minus", "without", "less", "losing", "loses",
              "dropping", "drops", "excluding", "lacking", "but not", "not", "-"],
    "reversed_all": ["all reversed", "all backwards", "the whole reversed", "all back", "all written backwards"],
    "reversed": ["reversed", "reversal", "backwards", "back", "in reverse", "<"],
    "anagrammed": ["anagrammed", "anagram", "*"],
    "reverse_of": ["a reversal of", "the reversal of", "reversal of", "reverse of", "a reverse of"],
    "anagram_of": ["an anagram of", "anagram of", "*"],
    "first letters": ["first letters of", "initial letters of", "the first letters of"],
    "first letter": ["first letter of", "initial letter of", "the first letter of",
                     "the initial letter of"],
    "last letters": ["last letters of", "the last letters of"],
    "last letter": ["last letter of", "final letter of", "the last letter of", "the final letter of"],
    "middle letters": ["middle letters of", "the middle letters of", "central letters of"],
    "middle letter": ["middle letter of", "central letter of", "the middle letter of"],
    "outer letters": ["outer letters of", "1st and last letters of", "the outer letters of", "first and last letters of",
                      "the first and last letters of"],
    "alternate letters": ["alternate letters of", "odd letters of", "even letters of",
                          "the odd letters of", "the even letters of", "every other letter of",
                          "every second letter of"],
    "trimmed": ["minus first letter", "minus last letter", "minus its first letter",
                "minus its last letter", "minus the first letter", "minus the last letter",
                "without its first letter", "without its last letter", "without the first letter",
                "without the last letter", "minus first and last letters", "minus outer letters",
                "minus last two letters", "minus first two letters", "minus middle letter",
                "minus middle letters", "minus its first and last letters", "curtailed",
                "beheaded", "shortened", "truncated"],
    "announce": ["envelope", "insertion", "charade", "container", "a charade", "an envelope",
                 "an insertion", "anagrind", "aind", "ind", "a combination of", "combination of",
                 "a composite of","a charade of", "charade of", "an envelope of", "envelope of", "an insertion of",
                 "insertion of", "a container of"],
}
BINARY = {"concat", "rconcat", "adjoin", "around", "inside", "minus"}
POSTFIX = {"reversed", "reversed_all", "anagrammed", "trimmed"}
#: Selections and trims give the letters the blog's caps already show
#: ([LAK]E, WA[S]); they only name the mechanism, and account for the brackets.
SELECT = {"first letter", "first letters", "last letter", "last letters", "middle letter",
          "middle letters", "outer letters", "alternate letters", "trimmed"}
PREFIX = {"reverse_of", "anagram_of"} | (SELECT - {"trimmed"})
#: What each operator makes the clue, as TYPE_PARTS names it.
PART = {"concat": "charade", "rconcat": "charade", "adjoin": "charade", "reversed_all": "reversal", "juxtapose": "charade", "around": "container",
        "inside": "container", "minus": "deletion", "reversed": "reversal", "reverse_of": "reversal",
        "anagrammed": "anagram", "anagram_of": "anagram", "cut": "deletion",
        "trimmed": "deletion", **{k: k for k in SELECT - {"trimmed"}}}
PART_ORDER = ["charade", "anagram", "container", "deletion", "reversal", "first letter",
              "first letters", "last letter", "last letters", "middle letter", "middle letters",
              "outer letters", "alternate letters"]
#: The standard abbreviations: R(un) is the convention R = run, where B[ail]
#: is a word cut short.
ABBREVIATIONS = ROOT / "tools" / "data" / "abbreviations.json"
ABBR = {k.lower(): {w.lower() for w in v}
        for k, v in json.loads(ABBREVIATIONS.read_text(encoding="utf-8"))["abbreviations"].items()}


def atom_flags(s):
    """What an atom's attached letters say it went through, as type parts.

    Bracketed letters are the ones not used, and that is a selection as often
    as a deletion: O[penly] R[evered] keeps first letters, {articl}E the last,
    C{ritica}L the outer ones, where {r}OSIER and PLUT{o} lose a letter or
    two. So the kept letters decide, and what they cannot decide is `cutp`,
    which names no type. R(un) and T{ime} are the abbreviations R and T."""
    whole = re.sub(r"[()\[\]{}]", "", s).lower()
    if whole in ABBR.get(atom_letters(s), ()):
        return frozenset()
    kinds = set()
    for word in s.split(" "):
        if not re.search(ATT, word):
            continue
        kept = [bool(re.fullmatch(rf"[{CAP}'’.\-]+", p)) for p in re.split(rf"({ATT})", word) if p]
        parts = [p for p in re.split(rf"({ATT})", word) if p]
        kept_letters = "".join(atom_letters(p) for p, k in zip(parts, kept) if k)
        cut = len(re.sub(r"[^A-Za-z]", "", word)) - len(kept_letters)
        shape = "".join("k" if k else "c" for k in kept)
        single = all(len(re.sub(r"[^A-Za-z]", "", p)) == 1 for p in parts)
        if single and len(parts) > 2 and re.fullmatch(r"c?(?:kc)+k?", shape):
            kinds.add("alternate letters")  # Z{o}E{e}A{r}L{y}, (d)A(m)N(i)N(g)
        elif re.fullmatch(rf"[{CAP}]\([a-z]+\)", word):
            kinds.add("cutp")  # Y(outh): the first letter, or the abbreviation Y
        elif len(kept_letters) == 1 and shape == "kc":
            kinds.add("first letter")
        elif len(kept_letters) == 1 and shape == "ck":
            kinds.add("last letter")
        elif len(kept_letters) == 1 and shape == "ckc":
            kinds.add("middle letter")
        elif len(kept_letters) == 2 and shape == "kck":
            kinds.add("outer letters")
        elif cut <= 2 or cut < len(kept_letters):
            kinds.add("cut")
        else:
            kinds.add("cutp")
    words = s.split(" ")
    if "alternate letters" in kinds and kinds <= {"alternate letters", "first letter", "last letter", "cutp"}:
        return frozenset({"alternate letters"})  # U(s) beside A(l)L(y) is one more alternate letter
    if len(words) > 1 and re.match(rf"{ATT}", words[0]) and re.search(rf"{ATT}$", words[-1]):
        return frozenset({"cutp"})  # [slipsh]OD ESSA[y]: a hidden word, which is no deletion
    if {"first letter"} == kinds and len([w for w in s.split(" ") if re.search(ATT, w)]) > 1:
        kinds = {"first letters"}
    if {"last letter"} == kinds and len([w for w in s.split(" ") if re.search(ATT, w)]) > 1:
        kinds = {"last letters"}
    if len(words) > 1 and "cut" in kinds:
        kinds.add("juxtapose")  # (F)UND O: pieces side by side, one of them cut
    return frozenset(kinds)


#: A gloss a blogger puts after an operator: the indicator it reads.
GLOSS_ONE = re.compile(r"\s*(?:or\s+)?(?:\((?P<p>[^()]{1,60})\)|\[(?P<b>[^\[\]]{1,60})\]|" + QUOTED + r")")


def _op_regex():
    alts = []
    for kind, words in OPS.items():
        for w in words:
            alts.append((len(w), kind, w))
    alts.sort(reverse=True)
    pat = "|".join(f"(?P<o{i}>{re.escape(w)}{'' if not w[-1].isalpha() else r'(?![a-z])'})"
                   for i, (_, _, w) in enumerate(alts))
    return re.compile(r"(?i)(?:" + pat + ")"), [(k, w) for _, k, w in alts]


OP_RX, OP_KINDS = _op_regex()
#: Where the wordplay stops and the blogger's prose starts.
PROSE_BREAK = re.compile(r"[.;](?=\s|$)|[!?](?=\s+[a-z]|\s*$)|\s[–—]\s|\s\|\s|:\s")


def strip_answer(line, answer):
    """The line without the answer the blogger opens it with, in whatever
    form: "{AS IF} –", "LEEWAY :", "CRITERIA RITE for…"."""
    at, got = re.match(r"\s*[{(]?", line).end(), ""
    for w in re.compile(rf"[{CAP}][{CAP}'’\-]*(?![a-z])").finditer(line, at):
        if line[at:w.start()].strip(" ") or len(got) >= len(answer):
            break
        got += atom_letters(w.group())
        at = w.end()
        if got == answer:
            sep = re.compile(r"[})]?\s*(?:[:–—=|]|\s-\s)?\s*").match(line, at)
            return line[sep.end():]
    return line


def wordplay_head(expl, answer):
    """The wordplay line of an explanation, answer and trailing prose cut off:
    the first line that is neither the answer, a number nor an enumeration."""
    for line in expl.split("\n"):
        line = line.replace("", "").replace("", "").replace(E_ON, "").replace(E_OFF, "").strip()
        letters = "".join(f for f in map(fold, line) if f.isalnum() and f.isascii())
        if not re.search(r"[a-zA-Z]", line) or letters == answer or re.fullmatch(r"\d+[ad]?", letters):
            continue
        line = re.sub(r"&nbsp;?", " ", line).strip()
        line = strip_answer(line, answer).lstrip("-–— ")
        # "Alternate letters (regularly) of": the gloss after the phrase.
        line = re.sub(r"(?i)\b(letters?|anagram|reversal|reverse|half)\s*(\([^()]*\)|\[[^\[\]]*\])\s+of\b",
                      r"\1 of \2", line)
        line = re.sub(r"(?i)^insert\s+(.{1,40}?)\s+(in|into|inside|between)\b", r"\1 \2", line)
        line = re.sub(rf"\s*=\s*[{CAP}][{CAP}\s'’\-]*\W*$", "", line)
        # Cut at the first break outside brackets.
        depth, cut = 0, len(line)
        for i, ch in enumerate(line):
            depth += ch in "([{"
            depth -= ch in ")]}"
            if depth == 0 and PROSE_BREAK.match(line, i) and not re.match(r"\.[A-Z]", line[i:i + 2]):
                cut = i
                break
        line = line[:cut].strip(" ,")
        # "CAKE with LAMB inserted" is CAKE around LAMB.
        line = re.sub(r"\b(?:with|has|having)\s+(.{1,40}?)\s+(?:inserted|put in|placed inside|inside)\b",
                      r"around \1", line)
        line = re.sub(r"\bwith\s+(.{1,40}?)\s+(?:removed|deleted|dropped|omitted|taken out|missing)\b",
                      r"minus \1", line)
        return line
    return ""


#: Words a blogger puts in front of an operator ("is placed around", "going
#: outside"); read past only where an operator follows.
FILLER = re.compile(r"(?i)(?:is|are|being|been|all|then|placed|put|goes|going|which|is then)\s+")
#: Quoted clue words used as their own letters: "of ‘is’ in NUANCE".
LITERAL = re.compile(r"['‘\"“](?P<w>[A-Za-z][a-z ]{0,20})['’\"”]")


APPOSITION = re.compile(r",\s*(?=an?\s+(?:anagram|reversal|envelope|insertion|charade|container|"
                        r"combination|subtraction|deletion)\b)")


class _Fail(Exception):
    """Where the wordplay stopped being wordplay."""
    def __init__(self, at=0):
        super().__init__(at)
        self.at = at


def _bracketed(s, i):
    """The index of the bracket closing the one at s[i], or -1."""
    d = 0
    for j in range(i, len(s)):
        d += s[j] in "([{"
        d -= s[j] in ")]}"
        if d == 0:
            return j
    return -1


def tokens(s, depth=0):
    """The wordplay as operands and operators; _Fail(at) on anything else."""
    out, i = [], 0
    while i < len(s):
        # "APTING, an anagram of ‘giant’ plus P": what APTING is made of.
        appo = APPOSITION.match(s, i)
        if appo and out and out[-1][0] in ("val", "group"):
            out.append(("bin", "equals"))
            i = appo.end()
            continue
        if s[i] in " ,\t":
            i += 1
            continue
        art = re.match(r"(?:A|An|The|a|an|the)\s+", s[i:])
        after = art and OP_RX.match(s, i + art.end())
        if after and OP_KINDS[int(after.lastgroup[1:])][0] not in BINARY:
            i += art.end()  # "A reversal (‘x’) of": the article is not the letter A
            continue
        op = OP_RX.match(s, i)
        if op and " " in op.group() and s[i] in "AaTt" and OP_KINDS[int(op.lastgroup[1:])][1][:2].lower() in ("a ", "an", "th"):
            m = None
        else:
            m = ATOM.match(s, i)
        if m:
            i = m.end()
            sourced = False
            while True:
                src = SOURCE.match(s, i)
                if src and (src.group("p") or src.group("q") or src.group("f") or src.group("e")
                            or re.search(r"[a-z]", (src.group("s") or "") + (src.group("b") or ""))):
                    i = src.end()
                    sourced = True
                    continue
                break
            flags = atom_flags(m.group())
            if len(atom_letters(m.group())) == 1 and not sourced and not flags:
                flags = frozenset({"bare"})  # K in ROO + K: a letter from somewhere unsaid
            full = atom_letters(re.sub(r"[()\[\]{}]", "", m.group())) if flags else None
            out.append(("val", atom_letters(m.group()), flags, full))
            continue
        lit = LITERAL.match(s, i)
        if lit and not OP_RX.fullmatch(lit.group("w")):
            out.append(("val", "".join(f for f in map(fold, lit.group("w")) if f.isalnum()), frozenset()))
            i = lit.end()
            src = SOURCE.match(s, i)
            if src and re.search(r"[a-z]", src.group()):
                i = src.end()
            continue
        if s[i] in "'‘’\"“”":
            i += 1
            continue
        if s[i] in "([{":
            j = _bracketed(s, i)
            if j < 0 or depth >= 3:
                raise _Fail(i)
            inner = s[i + 1:j]
            star_after = s[j + 1:j + 2] == "*"
            star_before = s[i - 1:i] == "*" and out and out[-1] == ("pre", "anagram_of")
            if out and out[-1][0] == "group" and s[i - 1:i] not in (" ", "\t") and re.fullmatch(r"[a-z]+", inner):
                raise _Fail(i)  # [OLI]{ves}: a group cut short, which nothing here models
            if inner.lstrip().startswith("*") or (
                    out and out[-1][0] == "group" and re.search(r"[a-z]", inner) and not star_after):
                i = j + 1  # the group's gloss: "(DOW[n] + SE[a]) (blue + ocean)"
                continue
            if star_after or star_before:
                letters = "".join(f for f in map(fold, inner) if f.isalnum() and f.isascii())
                if not letters:
                    raise _Fail(i)
                if star_before:
                    out.pop()
                out.append(("val", ("ana", "".join(sorted(letters))), frozenset({"anagram_of"})))
                i = j + 1 + star_after
                continue
            try:
                out.append(("group", tokens(inner, depth + 1)))
            except _Fail:
                raise _Fail(i)
            i = j + 1
            continue
        fill = FILLER.match(s, i)
        if fill and OP_RX.match(s, fill.end()):
            i = fill.end()
            continue
        if op:
            kind, w = OP_KINDS[int(op.lastgroup[1:])]
            i = op.end()
            if w == "*":
                kind = "anagrammed" if out and out[-1][0] in ("val", "group") else "anagram_of"
                star = STAR_GLOSS.match(s, i) or re.match(r"\s*[(\[]\s*\*[^()\[\]]*[)\]]", s[i:])
                if star:
                    i += star.end() if star.re is not STAR_GLOSS else star.end() - i
            else:
                while True:
                    g = GLOSS_ONE.match(s, i)
                    if not (g and re.search(r"[a-z]", g.group()) and s[g.end():g.end() + 1] != "*"):
                        break
                    i = g.end()
                if kind in POSTFIX and re.match(r"\s*of(?![a-z])", s[i:]):
                    kind = {"reversed": "reverse_of", "anagrammed": "anagram_of"}.get(kind, kind)
            if kind in POSTFIX and not (out and out[-1][0] in ("val", "group", "post")):
                kind = {"reversed": "reverse_of", "anagrammed": "anagram_of"}.get(kind, kind)
            if kind != "announce":
                out.append(("post" if kind in POSTFIX else "pre" if kind in PREFIX else "bin", kind))
            continue
        m = re.match(r"(?:the|a|an|of|or|The|An)(?![a-z])\s*", s[i:]) or (
            re.match(r"A\s+(?=[a-z])", s[i:]) if OP_RX.match(s, i + 2) else None)
        if m:
            i += m.end()
            continue
        raise _Fail(i)
    return out


CAP_SET = 400


def _concat(a, b):
    if a and b and isinstance(a[-1], str) and isinstance(b[0], str):
        return a[:-1] + (a[-1] + b[0],) + b[1:]
    return a + b


def _flat(v):
    return "".join(v) if all(isinstance(p, str) for p in v) else None


# A value is a tuple of pieces, each a string of letters in order, an
# ("ana", sorted letters) run in any order, or a ("ctn", sorted letters,
# value) run: shuffled letters with the value set somewhere inside them.

def _letters(v):
    return "".join(p if isinstance(p, str) else p[1] if p[0] == "ana" else p[1] + _letters(p[2])
                   for p in v)


def _reverse(v):
    return tuple(p[::-1] if isinstance(p, str) else p if p[0] == "ana" else ("ctn", p[1], _reverse(p[2]))
                 for p in reversed(v))


def _apply(kind, a, b=None):
    """Every value `kind` makes of the values a (and b)."""
    if kind in ("concat", "juxtapose"):
        return [_concat(a, b)]
    if kind == "rconcat":
        return [_concat(b, a)]
    if kind == "adjoin":
        return [_concat(a, b), _concat(b, a)]
    if kind == "equals":
        flat = _flat(a)
        return [a] if flat and _matches(b, flat) else []
    if kind in ("reversed", "reverse_of", "reversed_all"):
        return [_reverse(a)]
    if kind in SELECT:
        return [a] + [(x,) for x in _select(kind, _flat(a) or "") if x]
    if kind in ("anagrammed", "anagram_of"):
        return [(("ana", "".join(sorted(_letters(a)))),)]
    if kind in ("around", "inside"):
        outer, inner = (a, b) if kind == "around" else (b, a)
        s = _flat(outer)
        if s is None:
            if len(outer) == 1 and outer[0][0] == "ana":
                return [(("ctn", outer[0][1], inner),)]
            return []
        return [_concat(_concat((s[:k],), inner), (s[k:],)) for k in range(1, len(s))]
    if kind == "minus":
        s, t = _flat(a), _flat(b)
        if not s or not t:
            return []
        return [(r,) for r in _removals(s, t)]
    return []


def _select(kind, s):
    """The letters `kind` picks out of a whole word, where the blog wrote
    the word rather than the letters (last letter of ‘Washington’)."""
    if not s:
        return []
    mid = len(s) // 2
    return {"first letter": [s[0]], "last letter": [s[-1]], "outer letters": [s[0] + s[-1]],
            "middle letter": [s[mid]] if len(s) % 2 else [],
            "middle letters": [s[mid - 1:mid + 1]] if len(s) % 2 == 0 else [s[mid - 1:mid + 2]],
            "alternate letters": [s[::2], s[1::2]]}.get(kind, [])


def _removals(s, t, cap=20):
    """Every string left by taking the letters of t out of s, in order:
    INDICATES less A and E is INDICTS."""
    if not t:
        return {s}
    out = set()
    for k in range(len(s)):
        if s[k] == t[0]:
            for r in _removals(s[k + 1:], t[1:], cap):
                out.add(s[:k] + r)
                if len(out) >= cap:
                    return out
    return out


def _through(kind, ops):
    """The operators of a value after `kind` applies to it. A selection names
    what the brackets of its operand did, so they are no longer a deletion;
    pieces put together only to be shuffled are anagram fodder, not a charade."""
    if kind in SELECT:
        ops = ops - {"cut", "cutp", "first letter", "first letters", "last letter", "last letters",
                     "middle letter", "outer letters"}
    if kind in ("anagrammed", "anagram_of"):
        ops = ops - {"concat", "juxtapose", "rconcat", "adjoin"}
    return ops | {kind}


def _length(v):
    return len(_letters(v))


def _matches(v, answer):
    """Whether value `v` spells exactly `answer`."""
    if not v:
        return not answer
    p, rest = v[0], v[1:]
    if isinstance(p, str):
        return answer.startswith(p) and _matches(rest, answer[len(p):])
    n = len(p[1]) if p[0] == "ana" else len(p[1]) + _length(p[2])
    here, after = answer[:n], answer[n:]
    if len(here) < n or not _matches(rest, after):
        return False
    if p[0] == "ana":
        return "".join(sorted(here)) == p[1]
    m = _length(p[2])
    return any(_matches(p[2], here[k:k + m]) and "".join(sorted(here[:k] + here[k + m:])) == p[1]
               for k in range(1, n - m))


def _values(toks, limit):
    """{value: frozenset of operator kinds} over every reading of `toks`."""
    n = len(toks)
    memo = {}

    def unit(i, j):
        """Whether toks[i:j] is one operand with its own unary operators: a
        prefix or suffix binds to that, never to a run of pieces, so that
        "anagram of HERON after MO" is not also an anagram of all of it."""
        kinds = [t[0] for t in toks[i:j]]
        core = [k for k in kinds if k not in ("pre", "post")]
        return (len(core) == 1 and core[0] != "bin"
                and all(k == "pre" for k in kinds[:kinds.index(core[0])])
                and all(k == "post" for k in kinds[kinds.index(core[0]) + 1:]))

    def span(i, j):
        if (i, j) in memo:
            return memo[(i, j)]
        res = {}

        def add(vals, ops):
            for v in vals:
                if len(res) >= CAP_SET:
                    return
                if _length(v) <= 2 * limit + 4:
                    res.setdefault(v, set()).add(ops)
        memo[(i, j)] = res
        if j - i == 1:
            t = toks[i]
            if t[0] == "val":
                add([(t[1],)], frozenset(t[2]))
                if len(t) > 3 and t[3]:
                    # [vale]DICTION without VALE: the word before the cut.
                    add([(t[3],)], frozenset({"uncut"}))
            elif t[0] == "group":
                for v, opss in _values(t[1], limit).items():
                    for ops in opss:
                        add([v], ops)
            return res
        if toks[i][0] == "pre":
            wide = set() if unit(i + 1, j) else {"wide"}
            for v, opss in span(i + 1, j).items():
                for ops in opss:
                    add(_apply(toks[i][1], v), _through(toks[i][1], ops) | wide)
        if toks[j - 1][0] == "post":
            wide = set() if unit(i, j - 1) or toks[j - 1][1] == "reversed_all" else {"wide"}
            for v, opss in span(i, j - 1).items():
                for ops in opss:
                    add(_apply(toks[j - 1][1], v), _through(toks[j - 1][1], ops) | wide)
        for k in range(i + 1, j):
            if toks[k][0] == "bin" and i < k < j - 1:
                left, right = span(i, k), span(k + 1, j)
                for a, oa in left.items():
                    for b, ob in right.items():
                        for x in oa:
                            for y in ob:
                                add(_apply(toks[k][1], a, b), x | y | {toks[k][1]})
            if toks[k][0] != "bin" and toks[k - 1][0] != "bin" and toks[k][0] != "post" and toks[k - 1][0] != "pre":
                left, right = span(i, k), span(k, j)
                for a, oa in left.items():
                    for b, ob in right.items():
                        for x in oa:
                            for y in ob:
                                add(_apply("juxtapose", a, b), x | y | {"juxtapose"})
        return res

    return span(0, n) if n else {}


#: Prose that names an operation, which a type read off the wordplay before
#: it would leave out.
NAMES_AN_OPERATION = re.compile(
    r"(?i)revers|backward|anagram|\*|minus|without|\bless\b|losing|remov|delet|dropp|insert|"
    r"contain|around|\bround|inside|within|envelop|swallow|embrac|\bfirst|\blast|middle|letter|"
    r"\bhalf|\bmost|almost|\bcut|trim|behead|curtail|endless|headless|topless|tailless|homophone|"
    r"sounds|hidden|missing|omit|take away|taken|\bout\b|replac|substitut|swap|exchang|instead|chang")


def wordplay_type(expl, answer, body=""):
    """The clue type the write-up's wordplay spells out, when its pieces put
    together by its own operators give exactly the answer; else None. Every
    reading that gives the answer must use the same operators. A single
    letter the write-up does not source may have been picked out of a clue
    word ("ROO + K" for top of Kilkenny), so where the clue has a selecting
    word, such a reading names no type."""
    head = wordplay_head(expl, answer)
    if not head or re.search(r"(?i)hidden|homophone|sounds|spoon|lurk", head):
        return None
    try:
        toks = tokens(head)
    except _Fail as e:
        # Wordplay then prose ("{p}ROBIN{g} without its wings"): the wordplay
        # alone, if the prose names no operation it would have left out.
        rest = head[e.at:]
        if e.at == 0 or NAMES_AN_OPERATION.search(rest) or SELECTING.search(rest):
            return None
        try:
            toks = tokens(head[:e.at])
        except (_Fail, RecursionError):
            return None
    except RecursionError:
        return None
    if len(toks) > 16:
        return None
    if len(toks) == 1 and toks[0][0] == "val" and toks[0][1] == answer and toks[0][2] == {"cut"} \
            and " " not in head.strip():
        return "deletion"  # {r}OSIER, LO[g]IN: one word with letters taken off
    if not any(t[0] in ("bin", "pre", "post") or (t[0] == "val" and t[2]) for t in toks) \
            and sum(t[0] != "bin" for t in toks) < 2:
        return None
    hits = {frozenset(ops) for v, opss in _values(toks, len(answer)).items()
            if _matches(v, answer) for ops in opss}
    # An operator binds to the piece beside it unless only a wider reading
    # spells the answer: "anagram of HERON after MO" is MO + (HERON)*.
    if any("wide" not in ops for ops in hits):
        hits = {ops for ops in hits if "wide" not in ops}
    parts = {frozenset(PART[o] for o in ops if o in PART) for ops in hits}
    if len(parts) != 1 or any("cutp" in ops or ("bare" in ops and SELECTING.search(body)) for ops in hits):
        return None
    (p,) = parts
    if not p:
        return None
    # {articl}E + {o}N: two words each giving their last letter is "last letters".
    flat = [t for t in toks for t in (t[1] if t[0] == "group" else [t])]
    for one in ("first letter", "last letter"):
        if one in p and (one + "s" in p or sum(t[0] == "val" and one in t[2] for t in flat) > 1):
            p = (p - {one}) | {one + "s"}
    return " + ".join(x for x in PART_ORDER if x in p)


#: An operation the write-up names, then in parentheses the clue words that
#: indicate it: "<em>reversed</em> (backing)", "anagram (strangely) of",
#: "An envelope (‘amid’) of", "inside (“into”)".
IND_OP = re.compile(
    r"(?i)(?<![a-z])(?:anagram(?:med)?|reversal|reversed|reverse|backwards|envelope|insertion|"
    r"inside|within|into|around|round|containing|contained(?: in| by)?|holding|taking in|"
    r"inserted(?: in| into)?|minus|without|losing|removed|deleted|deletion|excluding|dropping|"
    r"hidden(?: answer| word)?(?: in)?|hiding in|lurker|lurking|homophone(?: of)?|sounds? like|sound-alike|"
    r"another(?=\s*\([^()]*\)\s+of)|"
    r"(?:first|last|middle|outer|inner|odd|even|alternate)\s+letters?(?: of)?|"
    r"after|following|followed by|next to|preceded by|before)(?:\s+of)?"
    r"\s*(?:/\s*['‘\"“”](?P<s>[^'‘’\"“”()]{1,50})['’\"”]"
    r"|\(\s*(?:or\s+)?(?:['‘\"“](?P<q>[^'‘’\"“”()]{1,50})['’\"”]|(?P<w>[^()]{1,50}))\s*\)"
    r"|\[\s*(?P<b>[^\[\]]{1,50})\s*\])")
#: An indicator the write-up names as one: "(indicated by treated)", "the
#: anagram indicator being “provided by”", "with ‘circulating’ signposting".
NAMED_IND = re.compile(
    r"(?i)(?:indicated by|indicator (?:is|being|here is)|anagrind (?:is|being)|signalled by)\s*"
    r"(?:['‘\"“](?P<q>[^'‘’\"“”()]{1,40})['’\"”]|(?P<w>[a-z][a-z' ]{0,30}?)(?=[).,;]|$))"
    r"|['‘\"“](?P<r>[^'‘’\"“”()]{1,40})['’\"”]\s+(?:is|as|being)\s+the\s+(?:\w+\s+)?(?:indicator|anagrind)"
    r"|with\s+['‘\"“](?P<t>[^'‘’\"“”()]{1,40})['’\"”]\s+(?:signposting|indicating|signalling)")
#: A gloss after letters picked out of or cut from a word, which names the
#: picking: "feeD (conclusion of)", "LAM(b) (‘tailless’)", "[initially lacking]".
CUT_GLOSS = re.compile(rf"(?:\w*[a-z][{CAP}]\w*|[{CAP}]\w*[a-z]\b|\S*{ATT}\S*)"
                       r"\s*(?:\(\s*(?P<p>[^()]{1,50})\)|\[\s*(?P<b>[^\[\]]{1,50})\])")
#: The anagram star glossed with its indicator: "(*changed)", "[* = to become …]".
STAR_GLOSS = re.compile(r"[(\[]\s*\*\s*=?\s*(?P<w>[a-z][^()\[\]]{0,50}?)\s*[)\]]")
ITALIC_OP = re.compile(E_ON + r"(?P<op>[^" + MARKS + r"()]{1,40})" + E_OFF +
                       r"\s*\(\s*(?:['‘\"“](?P<q>[^'‘’\"“”()]{1,50})['’\"”]|(?P<w>[^()]{1,50}))\s*\)")


#: Words in a block's clue words that say only part of them is used: the
#: letters were selected or cut, which the type must then name.
SELECTING = re.compile(
    r"(?i)\b(?:most|mostly|almost|nearly|endless(?:ly)?|half|first|initial(?:ly)?|final(?:ly)?|"
    r"last|head(?:less|s|ed)?|lead(?:er|ing|s)?|start|end(?:s|ing)?|finish|centre|center|heart|middle|"
    r"core|odd(?:ly|s)?|even(?:ly)?|regular(?:ly)?|alternate(?:ly)?|brief(?:ly)?|short|shortly|"
    r"little|bit|top(?:less|s|ped)?|tail(?:less|s|ed)?|trimmed|clipped|docked|cut|dropping|losing|without|missing|empty|"
    r"outside|edges?|borders?|extremes?|limits?|sides?|capital|opening|beginning|minus|"
    r"occasionally|periodically|conclusion|primarily|lacking)\b")


def selected(letters, src):
    """Whether a block's letters look picked out of its clue words ("cat
    finally" -> T, "most of the" -> TH) rather than meant by them ("was
    first" -> LED): a selecting word, and the letters in order in the rest."""
    hit = SELECTING.search(src)
    if not hit:
        return False
    rest = "".join(f for f in map(fold, src[:hit.start()] + src[hit.end():]) if f.isalnum())
    it = iter(rest)
    return all(ch in it for ch in atom_letters(letters))


def checked_type(expl, expl_marked, answer, blk, body=""):
    """The clue type, where the write-up's letters bear it out.

    A named anagram stands only where its fodder is in the write-up and
    holds the answer's letters, since "anagram" is said of every clue with
    one in it; a named homophone stands only where nothing is added to it.
    A spelled-out type stands only where no block's clue words say part of
    them was cut away, which the operators would then not have named."""
    named = clue_type(expl)
    head = wordplay_head(expl_marked, answer) if answer else ""
    if named == "anagram" and not has_fodder(expl, answer):
        named = None
    if named == "homophone" and (re.search(r"\+|\band\b|\bplus\b", head) or len(blk) > 1):
        named = None
    spelled = wordplay_type(expl_marked, answer, body) if answer else None
    if spelled and any(selected(letters, src) for letters, src in blk) and not re.search(
            r"deletion|letter", spelled):
        spelled = None
    return combined_type(named, spelled)


def has_fodder(expl, answer):
    """Whether the write-up holds the answer's letters in one run of caps or
    one bracketed group: the fodder of a whole-clue anagram. The answer
    itself, which the write-up prints, is not its own fodder."""
    runs = [m.group() for m in ATOM.finditer(expl)] + [
        m.group(1) for m in re.finditer(r"[(\[{]([^()\[\]{}]{2,60})[)\]}]", expl)
        if not re.match(r"[\[{(]?[A-Za-z]", expl[m.end():m.end() + 2])]  # [OLI]{ves} is cut fodder
    letters = [atom_letters(r) if r.upper() == r else
               "".join(f for f in map(fold, r) if f.isalnum() and f.isascii()) for r in runs]
    return any(x != answer and sorted(x) == sorted(answer) for x in letters)


def combined_type(named, spelled):
    """The type a write-up names and the one its wordplay spells out, as one.
    The spelled one is letter-checked, so it wins where it only adds parts to
    the named one; where they disagree, neither is a fact."""
    if not (named and spelled):
        return named or spelled
    if set(named.split(" + ")) <= set(spelled.split(" + ")):
        return spelled
    return None


def operation_indicators(expl_marked):
    """The glosses the write-up hangs on a named operation, italic or plain."""
    plain = expl_marked.replace(E_ON, "").replace(E_OFF, "")
    out = [m.group("q") or m.group("w") or m.group("s") or m.group("b") for m in IND_OP.finditer(plain)]
    out += [m.group("w") for m in STAR_GLOSS.finditer(plain)]
    out += [next(g for g in m.groups() if g) for m in NAMED_IND.finditer(plain)]
    for m in CUT_GLOSS.finditer(plain):
        for part in GLOSS_PARTS.split((m.group("p") or m.group("b")).strip(" '‘’\"“”")):
            if SELECTING.search(part):
                out.append(part.strip(" '‘’\"“”"))
    for m in ITALIC_OP.finditer(expl_marked):
        op = m.group("op").strip()
        if op and len(op.split()) <= 4 and not re.search(r"\d|[A-Z]{2}", op):
            out.append(m.group("q") or m.group("w"))
    out += [m.group(1) for m in ITALIC_IN_PARENS.finditer(expl_marked)
            if not re.search(rf"[{CAP}]\s*$", expl_marked[:m.start()])]  # BAG(<i>sack</i>) is a source
    return out


def indicators(blog, expl_marked, body, brackets, avoid=()):
    """Indicator words the blog's own convention marks, as spelled in `body`.
    `brackets` says whether this post's key declares [bracketed] indicators;
    `avoid` is what the clue's other words already are (definitions, block
    sources), which an indicator cannot also be."""
    marked = expl_marked.replace(U_ON, "").replace(U_OFF, "")
    raw = []
    if blog == "timesforthetimes" and brackets:
        raw += BRACKETED.findall(marked.replace(E_ON, "").replace(E_OFF, ""))
    raw += operation_indicators(marked)
    out = []
    for r in raw:
        parts = [p for p in ELLIPSIS.split(r) if p.strip()]
        found = [in_clue(p, body) for p in parts]
        if parts and all(found):
            out.extend(f for f in found if f not in out and not overlaps(f, avoid))
    return out


def overlaps(phrase, others):
    """Whether `phrase` is, or sits inside, or holds, one of `others`."""
    words = lambda t: " " + " ".join(re.findall(r"[\w'’]+", t.lower())) + " "
    p = words(phrase)
    return any(p in words(o) or words(o) in p for o in others)


# ---------------------------------------------------------------- the posts

def rendered(field):
    """A WordPress `rendered` field, whichever of three shapes a fetcher stored."""
    if isinstance(field, dict):
        return field.get("rendered", "")
    if isinstance(field, str) and field.startswith("{'rendered'"):
        try:
            return ast.literal_eval(field)["rendered"]
        except (ValueError, SyntaxError):
            return field
    return field or ""


NUMBER = re.compile(r"(?<![\d,])(\d{1,2},\d{3}|\d{3,6})(?![\d,])")


def post_numbers(title):
    return {int(n.replace(",", "")) for n in NUMBER.findall(html.unescape(title))}


def load_post(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return {"id": d["id"], "link": d.get("link"), "title": html.unescape(rendered(d.get("title"))),
            "content": rendered(d.get("content"))}


def puzzle_entries(p):
    """[(entry id, clue body, solution)] in the order blogs print them."""
    rows = [e for e in p["entries"] if clue_body(e.get("clue"))]
    rows.sort(key=lambda e: (e["direction"] != "across", e["number"]))
    return [(e["id"], clue_body(e["clue"]), e.get("solution") or "") for e in rows]


def align(entries, stream):
    """Per entry, the (start, end) of its clue's letters in `stream`'s projection.

    Clues are searched for in order from the last one found, which is the order
    blogs print them in; a clue not found after the cursor is looked for from
    the top once, and taken only if it occurs there exactly once."""
    letters = stream[0]
    hits, cursor = {}, 0
    for eid, body, _ in entries:
        key = projection(body)[0]
        if len(key) < 4:
            continue
        at = letters.find(key, cursor)
        if at < 0:
            first = letters.find(key)
            if first < 0 or letters.find(key, first + 1) >= 0:
                continue
            at = first
        hits[eid] = (at, at + len(key))
        cursor = at + len(key)
    return hits


#: Where a write-up moves on to the next clue: a line that is a clue number,
#: alone or with its direction, before anything but prose ("2 defs" is prose),
#: or an Across/Down heading. Bounds the explanation when the next clue itself
#: was not found.
NEXT_CLUE = re.compile(
    r"\n[ \t\ue000-\ue003]*(?:\d{1,2}(?:[ \t]*(?:a|d|ac|dn|across|down)\b)?[ \t.]*"
    r"(?=\n|[ \t]*[\"'‘“A-Z(\ue000-\ue003])|(?:across|down)\b)", re.I)


def facts_for_post(blog, entries, post):
    """{entry id: facts} for every clue of `entries` found in `post`."""
    text = flatten(post["content"])
    stream = projection(text, marked=True)
    letters, pos, under, _ = stream
    hits = align(entries, stream)
    brackets = bool(BRACKETS_ARE_INDICATORS.search(text))
    starts = sorted(a for a, _ in hits.values())
    out = {}
    for eid, body, solution in entries:
        if eid not in hits:
            continue
        a, b = hits[eid]
        nxt = next((s for s in starts if s >= b), len(letters))
        seg_start = pos[b - 1] + 1
        seg_end = pos[nxt] if nxt < len(letters) else len(text)
        expl_marked = text[seg_start:seg_end]
        cut = NEXT_CLUE.search(expl_marked, 1)
        expl_marked = expl_marked[:cut.start() if cut else 1200][:1200]
        expl_marked = detach_sources(expl_marked, body)
        expl = re.sub("[" + MARKS + "]", "", expl_marked)
        bpos = projection(body)[1]
        defs = spans_of(under[a:b], bpos, body)
        fact = {"found": True}
        if defs:
            fact["definition"] = defs
        elif defs is None:
            fact["badSpan"] = True
        answer = projection(solution)[0]
        blk = blocks(expl, body, answer, brackets) if answer else []
        t = checked_type(expl, expl_marked, answer, blk, body)
        if t:
            fact["type"] = t
        if blk and "hidden" not in (t or ""):
            fact["blocks"] = blk
        ind = indicators(blog, expl_marked, body, brackets,
                         avoid=(defs or []) + [src for _, src in blk])
        if ind:
            fact["indicators"] = ind
        out[eid] = fact
    return out


def _work(args):
    blog, path, candidates = args
    post = load_post(path)
    best = None
    for pid, entries in candidates:
        facts = facts_for_post(blog, entries, post)
        score = len(facts) / max(1, len(entries))
        if score >= MIN_ALIGNED and (best is None or score > best[1]):
            best = (pid, score, facts, len(entries))
    if best is None:
        return None
    return {"blog": blog, "post": post["id"], "url": post["link"], "id": best[0],
            "score": best[1], "facts": best[2], "clues": best[3]}


def load_puzzles(extra=()):
    """{number: [(id, entries)]} over our puzzles, plus any `extra` records."""
    by_number = collections.defaultdict(list)
    series = {}
    for path in puzzle_files():
        p = read_puzzle_file(path)
        ents = puzzle_entries(p)
        if ents:
            by_number[p["number"]].append((p["id"], ents))
            series[p["id"]] = p.get("series", "cryptic")
    for pid, number, ents, s in extra:
        by_number[number].append((pid, ents))
        series[pid] = s
    return by_number, series


def bigdave_records():
    """bigdave44's own parsed light lists, as stand-in puzzles to measure on
    until the Telegraph puzzles are filed. Ids are prefixed so nothing mistakes
    them for ours."""
    path = BLOGS["bigdave44"][0] / "parsed.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        ents = [(f"{e['number']}-{e['direction']}", clue_body(e.get("clue")),
                 e.get("answer") or "") for e in r["entries"] if clue_body(e.get("clue"))]
        if ents:
            out.append((f"bd:{r['series']}-{r['number']}", r["number"], ents, "bd:" + r["series"]))
    return out


def extract(blogs, with_bigdave_records=False, jobs=None):
    """Every post of `blogs` joined to the puzzle it writes up, with its facts.
    One record per puzzle: the post whose clues were found most completely."""
    extra = bigdave_records() if with_bigdave_records else ()
    by_number, series = load_puzzles(extra)
    work = []
    for blog in blogs:
        posts = BLOGS[blog][0] / "posts"
        for path in sorted(posts.glob("*.json")):
            try:
                title = rendered(json.loads(path.read_text(encoding="utf-8")).get("title"))
            except ValueError:
                continue
            cands = [c for n in post_numbers(title) for c in by_number.get(n, ())]
            if cands:
                work.append((blog, path, cands))
    best = {}
    if jobs == 1:
        results = map(_work, work)
    else:
        ex = ProcessPoolExecutor(jobs)
        results = ex.map(_work, work, chunksize=16)
    for r in results:
        if r and (r["id"] not in best or r["score"] > best[r["id"]]["score"]):
            best[r["id"]] = r
    if jobs != 1:
        ex.shutdown()
    return best, series


def inputs_digest():
    """A digest of everything the output is a function of: this file, each
    blog's cached posts, bigdave44's parsed light lists, and the clues of every
    puzzle. Posts are cached once and never rewritten, so a post is its name and
    size; a puzzle is only what the join reads, so a new annotation moves nothing."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    for blog in sorted(BLOGS):
        posts = BLOGS[blog][0] / "posts"
        names = sorted((e.name, e.stat().st_size) for e in os.scandir(posts)
                       if e.name.endswith(".json")) if posts.is_dir() else []
        h.update(json.dumps([blog, names]).encode())
    parsed = BLOGS["bigdave44"][0] / "parsed.jsonl"
    h.update(parsed.read_bytes() if parsed.exists() else b"")
    for path in puzzle_files():
        p = read_puzzle_file(path)
        h.update(json.dumps([p["id"], p["number"], p.get("series"), puzzle_entries(p)]).encode())
    return h.hexdigest()


# ------------------------------------------------------------------ outputs

def publishable(fact):
    """The facts of one clue that ship: what was found, minus the bookkeeping.

    More than one underlined span is a definition only as the two halves of a
    double definition; otherwise it is a split definition or a blogger's
    emphasis, and the site has no sentence that states it truthfully."""
    out = {k: fact[k] for k in ("definition", "type", "indicators") if k in fact}
    if fact.get("blocks"):
        out["blocks"] = [list(b) for b in fact["blocks"]]
    defs = out.get("definition", [])
    if len(defs) > 1 and not (len(defs) == 2 and out.get("type") == "double definition"):
        del out["definition"]
    return out


def write(best, series):
    OUT.mkdir(parents=True, exist_ok=True)
    by_series = collections.defaultdict(dict)
    for pid, r in best.items():
        if pid.startswith("bd:"):
            continue
        entries = {eid: publishable(f) for eid, f in sorted(r["facts"].items())}
        entries = {k: v for k, v in entries.items() if v}
        if entries:
            by_series[series[pid]][pid] = {"blog": r["blog"], "name": BLOGS[r["blog"]][1],
                                           "url": r["url"], "entries": entries}
    for old in OUT.glob("*.json"):
        if old.stem not in by_series:
            old.unlink()
    for s, rows in sorted(by_series.items()):
        (OUT / f"{s}.json").write_text(
            "{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(v, ensure_ascii=False, sort_keys=True)
                               for k, v in sorted(rows.items())) + "\n}\n", encoding="utf-8")
    return sum(len(v) for v in by_series.values())


def measure(best, series):
    rows = collections.defaultdict(collections.Counter)
    for pid, r in best.items():
        c = rows[(r["blog"], series[pid])]
        c["puzzles"] += 1
        c["clues"] += r["clues"]
        for f in r["facts"].values():
            c["found"] += 1
            c["definition"] += "definition" in f
            c["badSpan"] += "badSpan" in f
            c["type"] += "type" in f
            c["indicators"] += "indicators" in f
            c["blocks"] += "blocks" in f
    print("Percentages are of every clue in the joined puzzles.")
    print(f"{'blog':17} {'series':16} {'puzzles':>7} {'clues':>7} {'found%':>6} {'def%':>6} {'type%':>6} {'ind%':>6} {'blk%':>6} {'bad%':>5}")
    for (blog, s), c in sorted(rows.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        n = max(1, c["clues"])
        print(f"{blog:17} {str(s):16} {c['puzzles']:7} {c['clues']:7} {100 * c['found'] / n:6.1f} {100 * c['definition'] / n:6.1f} "
              f"{100 * c['type'] / n:6.1f} {100 * c['indicators'] / n:6.1f} {100 * c['blocks'] / n:6.1f} {100 * c['badSpan'] / n:5.1f}")


#: Hand-read truth for a spread of clues per blog and era: what each post
#: says the definition, blocks, indicators and type are. Scored by --score;
#: the parser was tuned on the dev rows, and the held-out rows say how well
#: that generalises. Posts the blogger wrote as prose count against recall.
GOLD = ROOT / "tools" / "blog_facts_gold.jsonl"


def _items(field, value):
    """A field of the facts as the set of things scored: spans, blocks as
    (letters, clue words), indicator words, the type's parts."""
    norm = lambda t: t.lower().replace("’", "'").strip()
    if field == "definition":
        return {norm(d) for d in value or ()}
    if field == "blocks":
        return {(atom_letters(l.upper()), norm(src)) for l, src in value or ()}
    if field == "indicators":
        return {w for i in value or () for w in re.findall(r"[\w'’]+", norm(i))}
    return {frozenset(value.split(" + "))} if value else set()


def score(path=GOLD):
    """Precision and recall per blog and field against the hand-read truth."""
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    by_number, _ = load_puzzles(bigdave_records())
    entries = {pid: ents for lst in by_number.values() for pid, ents in lst}
    tally = collections.defaultdict(collections.Counter)
    misses = []
    for r in rows:
        post = load_post(BLOGS[r["blog"]][0] / "posts" / r["post"])
        got = publishable(facts_for_post(r["blog"], entries[r["puzzle"]], post).get(r["entry"], {}))
        for field in ("definition", "blocks", "indicators", "type"):
            g, p = _items(field, r["gold"].get(field)), _items(field, got.get(field))
            c = tally[(r.get("split", "dev"), r["blog"], field)]
            c["tp"] += len(g & p)
            c["fp"] += len(p - g)
            c["fn"] += len(g - p)
            if p - g:
                misses.append(f"FP {r['blog']} {r['puzzle']} {r['entry']} {field}: {sorted(map(str, p - g))}")
            if g - p:
                misses.append(f"FN {r['blog']} {r['puzzle']} {r['entry']} {field}: {sorted(map(str, g - p))}")
    print(f"{'split':9} {'blog':17} {'field':11} {'P':>6} {'R':>6} {'tp':>4} {'fp':>4} {'fn':>4}")
    for (split, blog, field), c in sorted(tally.items()):
        pr = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else float("nan")
        rc = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else float("nan")
        print(f"{split:9} {blog:17} {field:11} {pr:6.2f} {rc:6.2f} {c['tp']:4} {c['fp']:4} {c['fn']:4}")
    return misses


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--blog", action="append", choices=sorted(BLOGS))
    ap.add_argument("--measure", action="store_true", help="print coverage per blog and series")
    ap.add_argument("--sample", type=int, help="print N random extractions to check by hand")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dump", help="also write every joined record, bookkeeping included, as JSON lines")
    ap.add_argument("--from-dump", help="read the joins from an earlier --dump instead of the caches")
    ap.add_argument("--jobs", type=int, help="worker processes (default: one per CPU); 1 parses in this process")
    ap.add_argument("--if-changed", action="store_true",
                    help="exit without parsing when no input has changed since the last write")
    ap.add_argument("--score", nargs="?", const=str(GOLD), metavar="GOLD",
                    help="score the parser against hand-read truth and exit (default %(const)s)")
    args = ap.parse_args()
    if args.score:
        print("\n".join(score(args.score)))
        return
    digest = inputs_digest()
    if args.if_changed and STAMP.exists() and STAMP.read_text().strip() == digest:
        print(f"blog facts are current: no post, clue or parser change since {STAMP.relative_to(ROOT)} was written")
        return
    if args.from_dump:
        lines = Path(args.from_dump).read_text(encoding="utf-8").splitlines()
        best = {r["id"]: r for r in map(json.loads, lines)}
        series = load_puzzles(bigdave_records())[1]
    else:
        best, series = extract(args.blog or sorted(BLOGS), with_bigdave_records=True, jobs=args.jobs)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            for r in best.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if args.measure:
        measure(best, series)
    if args.sample:
        rng = random.Random(args.seed)
        pool = [(r, eid, publishable(f)) for r in best.values() for eid, f in r["facts"].items()]
        pool = [p for p in pool if p[2]]
        for r, eid, f in rng.sample(pool, min(args.sample, len(pool))):
            print(json.dumps({"id": r["id"], "entry": eid, "url": r["url"], **f}, ensure_ascii=False))
    print(f"wrote blog facts for {write(best, series)} puzzles to {OUT.relative_to(ROOT)}")
    if not (args.blog or args.from_dump):
        STAMP.write_text(digest + "\n")


if __name__ == "__main__":
    main()
