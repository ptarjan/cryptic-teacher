#!/usr/bin/env python3
"""Hidden-letter devices: a letter per clue that spells a phrase.

Barred puzzles (Listener, Azed specials, Inquisitor, Genius) often hide a
message: each clue's wordplay gives one letter too many (`extra`) or too few
(`omitted`), or the clue prints a misprint (`misprint`), or the solver reads a
letter off the clue itself (`clue`), and those letters, in order, spell a phrase.
An annotation records its clue's letter as `hiddenLetter`; the puzzle records each
phrase as an item of `messages` (tools/data/puzzle.schema.json).

    python3 tools/hidden_messages.py flagged         # preambles naming a device, by series
    python3 tools/hidden_messages.py convert [--write] [id ...]
                                                     # fill the fields from existing annotations

`convert` reads each flagged, annotated puzzle's blocks against its answers: block
letters one more than the answer's give an extra letter, one fewer (or one
supplied by a block with no clue words) an omitted one. It writes a puzzle only when exactly one reading the preamble allows spells
dictionary words; every other flagged puzzle stays without `messages`, which the
ratchet (validate_annotations BACKLOG_MARKERS "messages") counts until the
backfill re-annotates it.
"""
import collections
import functools
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

#: $defs/hiddenLetterKind in tools/data/puzzle.schema.json copies this list.
KINDS = ["extra", "omitted", "misprint", "clue"]

LEXICON = TOOLS / "data" / "lexicon.tsv"


def letters(text):
    return re.sub(r"[^A-Z]", "", str(text or "").upper())


def entry_id(e):
    return f"{e['number']}-{e['direction']}"


def one_more(longer, shorter):
    """The letter whose deletion from `longer` leaves `shorter`, or None."""
    if len(longer) != len(shorter) + 1:
        return None
    for i in range(len(longer)):
        if longer[:i] + longer[i + 1:] == shorter:
            return longer[i]
    return None


def base_letters(ann, entry):
    """The word the clue defines, before any hidden-letter step: the
    alteration's `from` where the preamble alters entries, else the answer."""
    alt = (entry or {}).get("alteration")
    if isinstance(alt, dict) and alt.get("from"):
        return letters(alt["from"])
    return letters(ann.get("answer") or (entry or {}).get("solution"))


def letter_problems(ann, entry):
    """What is wrong with this annotation's `hiddenLetter`, as sentences."""
    hl = ann.get("hiddenLetter")
    if not isinstance(hl, dict):
        return []
    kind, letter = hl.get("kind"), hl.get("letter") or ""
    clue = (entry.get("clue") or {}).get("text") or ""
    out = []
    allowed = {"misprint": {"printed", "at"}, "clue": {"at"}}.get(kind, set())
    for key in ("printed", "at"):
        if key in hl and key not in allowed:
            out.append(f"hiddenLetter {kind} takes no `{key}`")
        if key in allowed and key not in hl:
            out.append(f"hiddenLetter {kind} needs `{key}`")
    if out:
        return out
    if kind in ("extra", "omitted"):
        got = entry_letter(ann, entry)
        if got is None or got[:2] != (kind, letter):
            gives = "+".join(letters(b.get("gives")) or "-" for b in ann.get("blocks") or [])
            out.append(
                f"hiddenLetter {kind} {letter}: the blocks give {gives} and the answer is "
                f"{base_letters(ann, entry)}, so " + (
                    f"the device's letter is {got[0]} {got[1]}" if got else
                    "they do not differ by one letter")
                + (". An extra letter is in the blocks and not the answer; an omitted one "
                   "is in the answer and not the blocks, or in a block with no clueFragment"))
    else:
        at = hl["at"]
        printed = hl["printed"] if kind == "misprint" else letter
        seen = clue[at].upper() if 0 <= at < len(clue) else None
        if seen != printed:
            out.append(f"hiddenLetter {kind}: the clue has {seen!r} at {at}, not {printed}"
                       + (f"; {printed} occurs at "
                          + ", ".join(str(i) for i, c in enumerate(clue) if c.upper() == printed)
                          if printed in clue.upper() else ""))
        if kind == "misprint" and hl["printed"] == letter:
            out.append(f"hiddenLetter misprint: printed and correct letter are both {letter}")
    return out


def clue_order(entries):
    """Entries as the paper lists their clues: across by number, then down."""
    return sorted(entries, key=lambda e: (e["direction"] != "across", e["number"]))


def message_letters(puzzle, msg):
    """(the letters `msg` reads in order, whether every clue it reads is annotated)."""
    import groups
    continuations = groups.leader_of(puzzle["entries"])
    got, complete = [], True
    for e in clue_order(puzzle["entries"]):
        if entry_id(e) in continuations or e["clue"].get("missing"):
            continue
        if msg.get("direction") and e["direction"] != msg["direction"]:
            continue
        ann = e.get("annotation")
        if not ann:
            complete = False
            continue
        hl = ann.get("hiddenLetter")
        if isinstance(hl, dict) and hl.get("kind") == msg.get("kind"):
            got.append(hl.get("printed") if msg.get("printed") else hl.get("letter"))
    return "".join(x or "" for x in got), complete


def message_problems(puzzle):
    """Each `messages` item must be spelt by its clues' hidden letters."""
    out = []
    for msg in puzzle.get("messages") or []:
        if msg.get("printed") and msg.get("kind") != "misprint":
            out.append(f"message {msg['text']!r}: `printed` reads misprints, and it "
                       f"reads {msg.get('kind')} letters")
            continue
        got, complete = message_letters(puzzle, msg)
        want = letters(msg.get("text"))
        if not complete:
            continue
        same = (sorted(got) == sorted(want) if msg.get("order") == "unordered"
                else got == want)
        if not same:
            where = f"{msg.get('direction')} " if msg.get("direction") else ""
            out.append(f"message {msg['text']!r}: the {where}clues' {msg.get('kind')} "
                       f"letters read {got or 'nothing'}, not {want}. Each clue that "
                       f"gives a letter needs `hiddenLetter`, in clue order")
    for e in puzzle["entries"]:
        hl = (e.get("annotation") or {}).get("hiddenLetter")
        if hl and not any(m.get("kind") == hl.get("kind") for m in puzzle.get("messages") or []) \
                and not names_device(puzzle.get("preamble")):
            out.append(f"{entry_id(e)}: hiddenLetter, but the preamble describes no "
                       f"hidden-letter device")
    return out


# --- preamble detection ------------------------------------------------------
#
# A preamble names a device when it says a letter per clue is extra, omitted,
# misprinted or read off the clue, AND reads those letters together. The
# second half keeps out puzzles whose extra letters are only discarded
# ("answers lose a letter before entry") and errata.

DEVICE_PATTERNS = {
    "misprint": r"\bmisprint",
    "extra": (r"\b(extra|surplus|redundant|superfluous|spare|additional|unwanted)\s+(letter|word)s?\b"
              r"|\bletters?\s+(superfluous|to\s+be\s+(disregarded|ignored|discarded))\b"
              r"|\bdiscarded\s+letters\b|\bletter\s+too\s+many\b|\bone\s+letter\s+more\b"
              r"|\bwordplay\b[^.]{0,60}\b(an?|one)\s+(extra|additional)\b"),
    "omitted": (r"\bomi(t|ts|tted|ssion|ssions)\b|\bmissing\s+letters?\b"
                r"|\bletters?\s+(missing|short|lacking)\b|\bone\s+letter\s+(short|fewer)\b"
                r"|\bwordplay\b[^.]{0,60}\b(lacks|leaves\s+out|excludes)\b"),
    "clue": (r"\b(first|initial|last|final)\s+letters?\s+of\s+(the\s+|each\s+|these\s+|all\s+)?"
             r"(clues|extra\s+words|superfluous\s+words|redundant\s+words)\b"
             r"|\bletter\s+has\s+(somehow\s+)?moved\b"),
}
#: The letters are read together: "in clue order", "these letters", "the
#: omissions". Without it a device word only discards letters ("answers lose a
#: letter before entry").
READ_TOGETHER = re.compile(
    r"\bin\s+(clue\s+)?order\b|\bclue\s+by\s+clue\b"
    r"|\b(these|such|the|discarded|extra|superfluous|additional|omitted|surplus)\s+(letters|omissions)\b"
    r"|\bfirst\s+letters\b|\bthese\s+(spell|form|give|generate|indicate|suggest|can)\b"
    r"|\b(spell|spells|spelt|spelled)\b", re.I)


def device_kinds(preamble):
    """The hidden-letter kinds a preamble names, in KINDS order; [] when it names
    none or never reads the letters together."""
    text = preamble or ""
    if not READ_TOGETHER.search(text):
        return []
    return [k for k in KINDS if re.search(DEVICE_PATTERNS[k], text, re.I)]


def names_device(preamble):
    return bool(device_kinds(preamble))


def check_preamble(puzzle):
    """The warning the ratchet counts (BACKLOG_MARKERS "messages"): a preamble
    naming a hidden-letter device, and no `messages`. Prefixed `puzzle:` so the
    ratchet counts it once per puzzle."""
    if puzzle.get("messages") or not any(e.get("annotation") for e in puzzle["entries"]):
        return []
    kinds = device_kinds(puzzle.get("preamble"))
    if not kinds:
        return []
    return [(f"puzzle: the preamble names a hidden-letter device ({', '.join(kinds)}), "
             f"and the puzzle has no messages. Give each clue's letter as its "
             f"annotation's `hiddenLetter` and the phrase they spell as the _ann "
             f"file's \"messages\"")]


# --- converter -----------------------------------------------------------------

#: Only the commonest words count when reading a run of letters as a phrase:
#: the whole lexicon holds enough short oddities to split most strings.
LEXICON_TOP = 40000
#: The only words under three letters a phrase may hold: the lexicon's other
#: short entries (ER, NT, ST) split almost any run of letters.
SHORT_WORDS = frozenset(["A", "I", "O", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE",
                         "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO",
                         "TO", "UP", "US", "WE"])


@functools.lru_cache(maxsize=1)
def lexicon():
    words = set()
    for line in LEXICON.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line:
            continue
        cols = line.split("\t")
        if len(cols) > 1 and cols[1].isdigit() and int(cols[1]) > LEXICON_TOP:
            continue
        w = letters(cols[0])
        if len(w) >= 3 or w in SHORT_WORDS:
            words.add(w)
    return words


def segment(run, max_words):
    """`run` as at most `max_words` lexicon words, longest first, or None."""
    words = lexicon()

    @functools.cache
    def go(i, left):
        if i == len(run):
            return ()
        if left == 0:
            return None
        for j in range(len(run), i, -1):
            if run[i:j] in words:
                rest = go(j, left - 1)
                if rest is not None:
                    return (run[i:j],) + rest
        return None
    return go(0, max_words)


DIRECTION_RE = {"across": re.compile(r"\bacross\b", re.I), "down": re.compile(r"\bdowns?\b", re.I)}


def spelling_directions(preamble):
    """The directions the preamble's spelling sentence names, or [None] for both."""
    for sentence in re.split(r"(?<=[.;])\s+", preamble or ""):
        if READ_TOGETHER.search(sentence):
            named = [d for d, r in DIRECTION_RE.items() if r.search(sentence)]
            if len(named) == 1:
                return named
    return [None]


def entry_letter(ann, entry):
    """The extra or omitted letter the blocks give, as (kind, letter), or None.
    Extra: the blocks give the answer's letters and one more. Omitted: they give
    one fewer, or supply it in the clue's one single-letter block with no clue
    words (letters the preamble supplies)."""
    blocks = ann.get("blocks") or []
    if any(b.get("soundsLike") for b in blocks):
        return None
    got = collections.Counter(letters("".join(b.get("gives") or "" for b in blocks)))
    base = collections.Counter(base_letters(ann, entry))
    if not got or not base:
        return None
    supplied = [letters(b.get("gives")) for b in blocks
                if not b.get("clueFragment") and len(letters(b.get("gives"))) == 1]
    if len(supplied) == 1:
        return "omitted", supplied[0]
    more, fewer = got - base, base - got
    if sum(more.values()) == 1 and not fewer:
        return "extra", next(iter(more))
    if sum(fewer.values()) == 1 and not more:
        return "omitted", next(iter(fewer))
    return None


def block_letters(ann, built):
    """The letters `ann`'s blocks should give when the wordplay builds `built`:
    one more for an extra letter, one fewer for an omitted one the blocks do
    not supply themselves."""
    hl = ann.get("hiddenLetter")
    if not isinstance(hl, dict) or hl.get("kind") not in ("extra", "omitted"):
        return built
    if hl["kind"] == "extra":
        return built + (hl.get("letter") or "")
    supplied = any(not b.get("clueFragment") and letters(b.get("gives")) == hl.get("letter")
                   for b in ann.get("blocks") or [])
    return built if supplied else built.replace(hl.get("letter") or "#", "", 1)


WORD_COUNT = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10}


def convert(puzzle):
    """(status, detail, new puzzle or None). status is converted, failed, ambiguous,
    or skip (not flagged, unannotated, already has messages)."""
    import groups
    kinds = device_kinds(puzzle.get("preamble"))
    if not kinds or puzzle.get("messages"):
        return "skip", "", None
    if not any(e.get("annotation") for e in puzzle["entries"]):
        return "skip", "unannotated", None
    wanted = [k for k in kinds if k in ("extra", "omitted")]
    if not wanted:
        return "failed", f"{'/'.join(kinds)}: no letters in blocks to read", None
    continuations = groups.leader_of(puzzle["entries"])
    found = {}
    for e in puzzle["entries"]:
        ann = e.get("annotation")
        if ann and entry_id(e) not in continuations:
            hit = entry_letter(ann, e)
            if hit:
                found[entry_id(e)] = hit
    m = re.search(r"\b(" + "|".join(WORD_COUNT) + r"|\d+)\s+words\b", puzzle.get("preamble") or "", re.I)
    # A stated count is of the phrase's words, which may be hyphenated
    # compounds, so allow two more pieces.
    max_words = (WORD_COUNT.get(m.group(1).lower()) or int(m.group(1))) + 2 if m else 6
    readings = []
    for kind in wanted:
        for direction in spelling_directions(puzzle.get("preamble")):
            scope = [e for e in clue_order(puzzle["entries"])
                     if entry_id(e) not in continuations and not e["clue"].get("missing")
                     and (direction is None or e["direction"] == direction)]
            if any(not e.get("annotation") for e in scope):
                continue
            run = "".join(found[entry_id(e)][1] for e in scope
                          if entry_id(e) in found and found[entry_id(e)][0] == kind)
            if len(run) < 4:
                continue
            words = segment(run, max_words)
            if words:
                readings.append((kind, direction, run, words))
    if not readings:
        return "failed", f"blocks give no {'/'.join(wanted)} run that spells words", None
    if len(readings) > 1:
        return "ambiguous", "; ".join(f"{k} {d or 'all'} {' '.join(w)}" for k, d, _, w in readings), None
    kind, direction, run, words = readings[0]
    out = json.loads(json.dumps(puzzle))
    for e in out["entries"]:
        hit = found.get(entry_id(e))
        if hit and hit[0] == kind and (direction is None or e["direction"] == direction):
            e["annotation"]["hiddenLetter"] = {"kind": kind, "letter": hit[1]}
    msg = {"text": " ".join(words), "kind": kind, "order": "clues"}
    if direction:
        msg["direction"] = direction
    if re.search(r"\b(below|beneath|under)\s+the\s+grid\b", puzzle.get("preamble") or "", re.I):
        msg["placement"] = "belowGrid"
    out["messages"] = [msg]
    return "converted", msg["text"], out


def _puzzles(ids):
    """Each named puzzle, or every puzzle whose preamble names a device. A file
    is parsed only once its text holds a preamble: most hold none."""
    from fetch_puzzle import read_puzzle_file, resolve_puzzle
    from puzzle_paths import puzzle_files
    paths = [resolve_puzzle(i) for i in ids] if ids else puzzle_files()
    for p in paths:
        if not ids:
            with open(p, encoding="utf-8") as f:
                head = f.read(6000)
            m = re.search(r'"preamble": ("(?:[^"\\]|\\.)*")', head)
            if not m or not names_device(json.loads(m.group(1))):
                continue
        yield p, read_puzzle_file(p)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    write = "--write" in rest
    ids = [a for a in rest if not a.startswith("--")]
    tally = collections.defaultdict(collections.Counter)
    for path, puzzle in _puzzles(ids):
        if cmd == "flagged":
            kinds = device_kinds(puzzle.get("preamble"))
            if kinds:
                ann = any(e.get("annotation") for e in puzzle["entries"])
                tally[puzzle["series"]]["annotated" if ann else "unannotated"] += 1
                print(f"{puzzle['id']}\t{'/'.join(kinds)}\t{'A' if ann else '-'}\t"
                      f"{puzzle['preamble'][:160]}")
        elif cmd == "convert":
            status, detail, new = convert(puzzle)
            if status == "skip" and detail != "unannotated":
                continue
            status = "unannotated" if status == "skip" else status
            tally[puzzle["series"]][status] += 1
            print(f"{puzzle['id']}\t{status}\t{detail}")
            if write and new is not None:
                from fetch_puzzle import write_puzzle_file
                write_puzzle_file(path, new)
        else:
            raise SystemExit(f"hidden_messages: unknown command {cmd!r}")
    for s, c in sorted(tally.items()):
        print(f"# {s}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
