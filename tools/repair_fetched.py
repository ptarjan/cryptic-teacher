#!/usr/bin/env python3
"""Repair puzzle files that were written before the fetcher learned better.

    python3 tools/repair_fetched.py                          # say what is wrong, change nothing
    python3 tools/repair_fetched.py --apply                   # write the repairs
    python3 tools/repair_fetched.py --learned                 # only the clue-text mends learned from rereads
    python3 tools/repair_fetched.py --series cryptic          # one series only
    python3 tools/repair_fetched.py --from 27600 --to 27900   # one stretch of numbers
    python3 tools/repair_fetched.py --series cryptic --from 27600 --apply

Every defect below is one tools/fetch_puzzle.py refuses when it writes a file.
Files already on disk can still hold one — a long archive walk runs for days on
the code it started with — so this applies the same rules to what is stored, by
calling the fetcher's own functions rather than restating them: a repair that
disagreed with the fetcher would be a third opinion about what a puzzle file may
hold.

WHAT IT REPAIRS

Accented or mixed-case solutions. A cell holds one bare capital, so "ACORUÑA",
"eVEREST" and "office" are not what a solver writes. Normalised through
fetch_puzzle.bare_letters, which strips accents and raises case and touches
nothing else.

Masked solutions. An unexpired prize puzzle serves the SHAPE of an answer with
its letters withheld — "T?S?R" — and one masked light means the page is not
serving a key at all. So the whole puzzle goes unsolved, exactly as convert()
does it: half a key advertised as a full one is worse than none, and unsolved is
the state --refresh-unsolved already knows how to fill in later. A model's blind
solve is never at risk here, because tools/apply_solution.py writes bare letters
only, so nothing it wrote can read as masked.

Lights that were never part of a linked answer. A light whose own clue counts its
own cells in full is a finished answer, whatever group the paper put it in — it
is the parser reading wordplay as a cross-reference. Cryptic-27,884's 20-across
"See 5 across out to find another date (10)" got grouped with 5-across LURCHED
"(7)", storing RESCHEDULE as part of a seventeen-letter answer nobody wrote.
fetch_puzzle.dissolve_false_groups weighs that per light and not per group, so a
stranger hung off a real quotation leaves alone and the quotation keeps its other
lights; a group with nothing left that carries a clue goes whole. A bare "See 22"
leg never counts as the stranger, however the paper counted it. Gated off for the
series that genuinely enumerate light by light, so no Cyclops group is touched.

Linked answers the paper never grouped. The same markup that invented links also
lost real ones, leaving an enumeration that counts more letters than the lights
it was given — cryptic-23,816's 9-across TREAD "(5,3,6)" over five cells, with THE
BOARDS in 10-across under the clue "See above" and in no group at all.
fetch_puzzle.reconstruct_groups puts back the lights the counts cut into, taking
only lights the paper itself left spare (a pointer naming the clue, or no clue at
all) and only when the enumeration settles which — one membership that fits it,
or, where several hold the letters it counts, the one the clue list puts next
after the clue. A tie that survives both is left alone: a guess would be stored
as fact.

Link words filed as wordplay leaves. A letterless unchecked leaf in a charade
whose note says surface padding or joining words is a link word, and linkWords
is derived from the clue words nothing covers, so the repair is to take the leaf
out (--padding-only does just this). Left alone: other jobs in the note,
pronouns, placeholders, long phrases, and clues where padding is most of the
words; the tree must give the same answer after.

Word breaks an OCR'd count lost. A file tools/file_archive_org_puzzles.py filed
may print "(13)" for a light the paper counted "(8,5)". restore_word_breaks gives
it the breaks other puzzles print for the same letters (fetch_puzzle.
lost_word_breaks, from tools/data/answer_breaks.json: --write-breaks reads it off
the corpus's other files), and a light they print both ways, settling on neither,
is left, flagged for a read of the print (--write-flags). Letters alone never
decide it: a lexicon cut of the answer cut half the real one-word answers
the lexicon lacks. Marks an OCR left in a clue text (a
stray "·", a "." run on to the next word, a run of spaces) are mended as
punctuation.mend_puzzle and enumeration.collapse_entry_spaces mend them.
The edition queue writes each reading through mechanical(), so a re-read never
files what this would mend.

WHAT IT ONLY REPORTS

A mis-filed date. convert() refuses a page whose two stated dates are more
than a month apart — /crosswords/cryptic/1183 serves Quiptic 1,183 under a date
of 1934-01-18 — but a stored file keeps only the one date, so the second
statement is gone and there is nothing left to compare it against. What survives
is the shape of a series: numbers and dates climb together, so a file whose date
its own numeric neighbours contradict by more than that same month is mis-filed.
Reported, never rewritten. The real date is on the publisher's page, and a date
interpolated from neighbours would be a plausible-looking fiction in a field the
archive, the sitemap and every "puzzles from 2016" page all read as fact. Fix
one by re-fetching that single puzzle — but not while a walk is working through
its number, or the two will write the same file.

FLAGS

--apply      write the repairs; without it nothing is written at all
--dry-run    the default, and accepted so a caller can say what it means
--series     limit to one series key ("cryptic", "quiptic", "everyman", …)
--from, --to limit to a range of puzzle numbers, either end on its own allowed

Files are read and written through fetch_puzzle's own reader and writer, which
keeps each file's own source.acquiredBy: the tool that ACQUIRED a puzzle is
a fact about where it came from, which repairing it does not change. That is
write_puzzle_file's default, so nothing here names a generator. A file with
nothing wrong is never opened for writing, so it cannot be reformatted by being
looked at.

Not reindexed afterwards. Blanking a masked puzzle's solutions changes what
puzzles/index.json says about it, and this deliberately leaves that to
`python3 tools/fetch_puzzle.py --reindex` — the index is rebuilt from the whole
corpus, and rebuilding it here would race any fetch that is running.
"""
import argparse
import bisect
import collections
import contextlib
import copy
import re
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import enumeration
import fetch_puzzle as fetcher  # the rules being applied live there
import groups
import lesson_checks
import punctuation
import puzzle_paths
from groups import entry_id
import series as series_meta


def normalise_solutions(puzzle):
    """Bare capitals in every solution. Returns the ones that were not."""
    changed = []
    for entry in puzzle["entries"]:
        was = entry.get("solution")
        now = fetcher.bare_letters(was)
        if now != was:
            entry["solution"] = now
            changed.append((entry_id(entry), was, now))
    return changed


def unmask_solutions(puzzle):
    """Take the whole puzzle unsolved if any one light is masked.

    The letters are withheld, not wrong, so there is nothing to repair them to;
    what convert() does with such a page is store no solutions at all, and this
    does the same to a stored one. Run AFTER normalise_solutions,
    as in convert(), so an accent is not mistaken for a mask.
    """
    masked = [(entry_id(e), e["solution"]) for e in puzzle["entries"]
              if e.get("solution") and not fetcher.is_bare_letters(e["solution"])]
    if not masked:
        return []
    print(f"WARNING: {puzzle['id']}: solution masked on "
          + ", ".join(f"{eid} {sol!r}" for eid, sol in masked)
          + f" — storing all {len(puzzle['entries'])} entries UNSOLVED",
          file=sys.stderr)
    for entry in puzzle["entries"]:
        entry["solution"] = None
    return masked


def dissolve(puzzle):
    """Break up groups that are not linked answers. Returns the ones broken.

    The fetcher's own rule and its own cyclops gate, called rather than copied.
    It reads the per-light shape, every member carrying its group, so repair()
    spreads the stored leader-only groups before calling it.
    """
    return fetcher.dissolve_false_groups(puzzle["entries"], series_meta.of(puzzle))


def rebuild(puzzle):
    """Reassemble linked answers the paper left short. Returns the groups rebuilt.

    The fetcher's own rule, called where convert() calls it: after dissolve, which
    is what settles whether a link is real before anything is rebuilt from one.
    """
    return fetcher.reconstruct_groups(puzzle["entries"], series_meta.of(puzzle))


#: The filer whose OCR'd files the two repairs below mend: a printed count and
#: a clue's marks are only ever misread in a file a reader wrote.
ARCHIVE_FILER = "tools/file_archive_org_puzzles.py"


def read_by_archive_filer(puzzle):
    """Whether tools/file_archive_org_puzzles.py acquired `puzzle` (an OCR'd
    newspaper page)."""
    return (puzzle.get("source") or {}).get("acquiredBy") == ARCHIVE_FILER


def restore_word_breaks(puzzle):
    """Give the bare count of each phrase answer its word breaks. Returns the
    (light, was, now) of the ones restored.

    An OCR'd count often loses its commas: a light printed "(8,5)" filed as
    "(13)". Only a count the grid gave (clue "countFrom": "grid": no reader's
    enumeration survived) is restored; a bare count a reader read is the
    print's own and stays. The same letters are the same phrase in every puzzle that clues
    them, so the breaks come from there (fetch_puzzle.settled_breaks), hyphens
    and all; a light the other puzzles print both ways is left for the print
    (flagged_word_breaks)."""
    by_id = {entry_id(e): e for e in puzzle["entries"]}
    restored, done = [], []
    for eid, now in fetcher.lost_word_breaks(puzzle).items():
        if now is None:
            continue
        e = by_id[eid]
        was = e["clue"]["enumeration"]
        e["clue"] = {k: v for k, v in {**e["clue"], "enumeration": now}.items() if k != "countFrom"}
        # The restored break can make a known apostrophe answer ("WHAT'S THE BIG
        # IDEA", 5,3,3,4) count as said-but-unspelt on an annotated clue, which the
        # validator refuses (spelling.unsaid): write the spelling with the break.
        ann = e.get("annotation")
        if isinstance(ann, dict) and e.get("solution"):
            said = lesson_checks.spelling_unsaid(ann, e["solution"], now)
            if said:
                ann["spelling"] = said
        restored.append((eid, was, e["clue"]["enumeration"]))
        done.append(e)
    fetcher.enumeration_separators(done)
    return restored


def flagged_word_breaks(puzzle):
    """The lights of `puzzle` whose bare count the other puzzles print both
    ways, settling on neither: only the print says."""
    return [eid for eid, now in fetcher.lost_word_breaks(puzzle).items() if now is None]


def write_breaks(path=None):
    """Write the BREAKS file (fetch_puzzle.BREAKS, or `path`) from the files
    this corpus holds that no OCR reader wrote: every unlinked answer's
    printed enumerations, {enumeration: puzzles}, settled by
    fetch_puzzle.settled_breaks into {"breaks", "mixed"}. Returns
    (answers settled, answers mixed)."""
    seen = {}
    for p in fetcher.puzzle_files():
        puzzle = fetcher.read_puzzle_file(p)
        if read_by_archive_filer(puzzle):
            continue
        for e in puzzle.get("entries") or ():
            enum, solution = (e.get("clue") or {}).get("enumeration") or "", e.get("solution")
            if (solution and len(e.get("group") or ()) <= 1 and re.fullmatch(r"\d+(?:[,-]\d+)*", enum)
                    and sum(enumeration.counts(enum)) == len(solution)):
                seen.setdefault(solution, Counter())[enum] += 1
    breaks, mixed = {}, []
    for solution, printed in sorted(seen.items()):
        settled = fetcher.settled_breaks(printed)
        if settled:
            breaks[solution] = settled
        else:
            broken = sum(n for e, n in printed.items() if not re.fullmatch(r"\d+", e))
            if broken >= 2 and broken >= sum(printed.values()) - broken:
                mixed.append(solution)
    Path(path or fetcher.BREAKS).write_text(
        json.dumps({"breaks": breaks, "mixed": mixed}, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8")
    return len(breaks), len(mixed)


#: The archive.org files flagged_word_breaks leaves for a read of the print:
#: {"at": when the sweep found them, "ids": [puzzle id]}. The queue
#: (file_archive_org_puzzles.settled) never skips an edition holding one.
FLAGS = Path(__file__).resolve().parent / "data" / "word_break_flags.json"


def write_flags(path, ids):
    """Write `ids` as the FLAGS file at `path`, stamped now."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    Path(path).write_text(json.dumps({"at": now, "ids": sorted(set(ids))}, indent=1) + "\n")


def mend_clue_marks(puzzle):
    """Cut each clue's runs of spaces to one and make punctuation's certain
    mends (a stray "·", a "." run on to the next word), in place, annotation
    and italics moved with the words. Returns {light: its clue now}. A clue
    these mends would leave one the write gate refuses stays as it was
    (punctuation.unmend_refused): mended, its held file's write went whole."""
    before = {entry_id(e): copy.deepcopy(e) for e in puzzle["entries"]}
    spaced = {entry_id(e): e["clue"]["text"] for e in puzzle["entries"]
              if isinstance(e.get("clue"), dict) and enumeration.collapse_entry_spaces(e)}
    return punctuation.unmend_refused(puzzle, before, {**spaced, **punctuation.mend_puzzle(puzzle)})


def offsets(old, new):
    """[new offset of each old offset 0..len(old)] for `old` rewritten as
    `new`: kept characters move with their block, an edited stretch's
    offsets land at the start of what replaced it."""
    import difflib
    at = [0] * (len(old) + 1)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for i in range(i1, i2 + 1):
            at[i] = j1 + (i - i1 if tag == "equal" else 0)
    at[len(old)] = len(new)
    return at


#: Rules of clue_repair.mend_steps that --mends leaves out, found by reading the
#: dry run's diffs on held text. None now: mend_words (11 of 69 changes wrong:
#: "de rigueur" -> "bede rigueur", "to le" -> "tole", "haled" -> "hated") and
#: lead_speck (2 of 31: "D Day," lost its D, "1 Down's poet?" its reference)
#: were tightened in clue_repair until none of those changes is made.
EXCLUDED_MENDS = frozenset()
#: With --only: the mend_steps rules --mends leaves out so that only the named ones run.
ONLY_SKIP = frozenset()
#: Per-rule changes the last --mends run made: [(puzzle id, light, rule, was, now)].
MEND_LOG = []


def mend_clue_text(puzzle, learned_only=False, skip=(), log=None):
    """Mend each clue's text by clue_repair.mend_text (the count left after
    its words, a neighbour's count and number run into it, a drop capital, a
    word broken by a space, a one-letter misread of a word nobody prints),
    in place, annotation and italics moved with the words. Returns {light:
    its clue now}. The lights fetch_puzzle.clue_leftovers names are mended
    by the same function, so what it reports and what this repairs agree.
    `learned_only`: just clue_repair.learned_mends, the rules measured on the
    rereads (tools/learn_postproc.py), none of the older ones."""
    import clue_repair
    is_word, uses = clue_repair.lexicon()
    done = {}
    lights = {e["number"] for e in puzzle.get("entries") or () if isinstance(e.get("number"), int)}
    for e in puzzle.get("entries") or ():
        clue = e.get("clue") if isinstance(e.get("clue"), dict) else {}
        enum = clue.get("enumeration")

        def mapper(text, enum=enum, e=e):
            if learned_only:
                new = clue_repair.learned_mends(text, enum, is_word, lights)
            elif skip or log is not None:
                new, last = text, text
                for rule, new in clue_repair.mend_steps(text, enum, is_word, uses, lights=lights, skip=skip):
                    if log is not None and new != last and text == clue.get("text"):
                        log.append((puzzle.get("id"), entry_id(e), rule, last, new))
                    last = new
            else:
                new = clue_repair.mend_text(text, enum, is_word, uses, lights=lights)
            return new, offsets(text, new)

        if enumeration.rewrite_entry(e, mapper):
            done[entry_id(e)] = e["clue"]["text"]
    return done


def mechanical(puzzle, filer=None):
    """(puzzle mended, notes): the repairs above, on a copy, for an archive.org
    filer's file (or any puzzle `filer`, the tool about to write it, names
    so); any other file comes back as it was. The queue writes each
    reading through this (tools/scan_queue.file_puzzle), so a re-read never
    files what the sweep would have mended."""
    if any("number" not in e or "direction" not in e for e in puzzle.get("entries") or ()):
        return puzzle, []  # not a laid-out puzzle (a reading mid-build): nothing to name a light by
    if not (read_by_archive_filer(puzzle) or filer == ARCHIVE_FILER):
        return puzzle, []
    fixed = copy.deepcopy(puzzle)
    notes = []
    before = {entry_id(e): copy.deepcopy(e) for e in fixed["entries"]}
    marks = mend_clue_marks(fixed)
    if marks:
        notes.append(f"{len(marks)} clue(s) with stray marks or spaces mended")
    # A slip's mend that leaves its clue one the write gate refuses stays unmade (punctuation.unmend_refused).
    texts = mend_clue_text(fixed)
    texts = punctuation.unmend_refused(fixed, before, texts) if texts else texts
    if texts:
        notes.append(f"{len(texts)} clue(s) with a scan's slips mended: " + ", ".join(sorted(texts)))
    breaks = restore_word_breaks(fixed)
    if breaks:
        notes.append(f"{len(breaks)} word-break count(s) restored: "
                     + ", ".join(f"{eid} ({was})->({now})" for eid, was, now in breaks))
    return (fixed, notes) if notes else (puzzle, [])


def misfiled_dates(dated):
    """Which of a series' puzzles are dated against the run of their own numbers?

    `dated` is (number, datetime.date or None) for one series, and the rule it is weighed
    against is that the two climb together: puzzle n+1 is never published before
    puzzle n. So the dates that CAN all be true together are a non-decreasing
    subsequence, and the longest one is the reading that calls fewest files
    liars. Everything outside it is dated against its neighbours.

    Being outside it is not yet evidence of mis-filing — one paper's numbering
    hiccup puts a puzzle a day out — so each candidate is then measured against
    the window its surviving neighbours leave it: the date of the last good
    puzzle below it and the first good one above. Only a date more than
    fetch_puzzle.MISFILED outside that window is reported, which is the same
    month convert() refuses a live page for.

    Returns {number: (stored, earliest, latest)}, the bounds being None where
    there is no neighbour on that side.
    """
    seq = [(n, d) for n, d in sorted(dated) if d is not None]
    if not seq:
        return {}

    # Longest non-decreasing subsequence by date, over numbers in order.
    tails, tail_at, came_from = [], [], [-1] * len(seq)
    for k, (_n, d) in enumerate(seq):
        at = bisect.bisect_right(tails, d)
        if at == len(tails):
            tails.append(d)
            tail_at.append(k)
        else:
            tails[at], tail_at[at] = d, k
        came_from[k] = tail_at[at - 1] if at else -1
    keep, k = set(), tail_at[-1]
    while k != -1:
        keep.add(k)
        k = came_from[k]

    flagged = {}
    for k, (number, stored) in enumerate(seq):
        if k in keep:
            continue
        below = [seq[j][1] for j in keep if j < k]
        above = [seq[j][1] for j in keep if j > k]
        earliest = max(below) if below else None
        latest = min(above) if above else None
        out_by = max((earliest - stored) if earliest is not None else timedelta(0),
                     (stored - latest) if latest is not None else timedelta(0))
        if out_by > fetcher.MISFILED:
            flagged[number] = (stored, earliest, latest)
    return flagged


#: An archive.org FT page url's edition title: "Jul 16 1975, Financial Times, #26722, UK (en)".
FT_EDITION_URL = re.compile(r"/details/([^/]+)/([^/]+)/page/")
FT_EDITION_TITLE = re.compile(r"([A-Z][a-z]{2}) (\d\d?) (\d{4}), Financial Times, #(\d+)")


def ft_edition(url):
    """(item, "<date>_<issue>" edition dir name) of an archive.org FT page
    `url`, or None."""
    import urllib.parse
    m = FT_EDITION_URL.search(url or "")
    t = m and FT_EDITION_TITLE.match(urllib.parse.unquote(m.group(2)))
    if not t:
        return None
    try:
        when = datetime.strptime(f"{t[1]} {t[2]} {t[3]}", "%b %d %Y").date()
    except ValueError:
        return None
    return m.group(1), f"{when.isoformat()}_{t[4]}"


def misdated_ft(rows, listing=lambda item: ()):
    """[(number, stored, fixed, clash, why)] of the FT puzzles `rows`
    ([(number, date, source url)]) whose date clashes: a Sunday (the FT
    printed none), a day another number is dated, or not strictly between
    the dates of the puzzles numbered either side. `fixed` is the day those
    two count to, six issues a week (file_archive_org_puzzles.issue_step),
    when they agree, it is free and its year the stored one's, and the
    edition's issue neighbours (issue_dated over `listing(item)`, its
    item's edition dir names) do not vouch for a stored weekday no other
    number holds (then the number is the misread); else None and `why`
    says what stands in the way. The filer weighs a new title the same way
    (file_archive_org_puzzles.ft_dated)."""
    import file_archive_org_puzzles as archive
    held = {n: d for n, d, _ in rows if d is not None}
    urls = {n: url for n, _, url in rows}
    on_day = {}
    for n, d in held.items():
        on_day.setdefault(d, []).append(n)
    nums = sorted(held)
    out = []
    for k, n in enumerate(nums):
        stored = held[n]
        lo = nums[k - 1] if k else None
        hi = nums[k + 1] if k + 1 < len(nums) else None
        others = [m for m in on_day[stored] if m != n]
        clash = []
        if stored.weekday() == 6:
            clash.append("a Sunday")
        if others:
            clash.append(f"No {others[0]}'s day")
        if lo is not None and held[lo] >= stored or hi is not None and held[hi] <= stored:
            clash.append("out of order with " + " and ".join(
                f"No {m} on {held[m]}" for m in (lo, hi) if m is not None))
        if not clash:
            continue
        counted = {archive.issue_step(held[m], n - m) for m in (lo, hi) if m is not None}
        edition = ft_edition(urls.get(n))
        issue = edition and archive.issue_dated(edition[1], date_of(edition[1]), listing(edition[0]))
        fixed, why = None, ""
        if lo is None or hi is None or len(counted) != 1:
            why = "its numbered neighbours do not count to one day"
        elif (day_ := counted.pop()) == stored:
            why = "its numbered neighbours count to its day: the other number there is the misdated one"
        elif day_.weekday() == 6 or on_day.get(day_) or day_.year != stored.year:
            why = f"its numbered neighbours count to {day_}, {'a Sunday' if day_.weekday() == 6 else 'taken' if on_day.get(day_) else 'another year'}"
        elif issue and issue[2] and issue[0] == stored and stored.weekday() != 6 and not others:
            why = f"its edition's issue neighbours vouch for {stored}: the number may be the misread"
        else:
            fixed = day_
        out.append((n, stored, fixed, "; ".join(clash), why))
    return out


def date_of(name):
    """The date of a "<date>_<issue>" edition dir name."""
    from datetime import date
    return date.fromisoformat(name[:10])


def repair_ft_dates(apply_it=False):
    """misdated_ft over every ftcryptic file, the archive.org edition cache's
    listings weighing each edition's issue; each `fixed` one is written
    with its new date when `apply_it`."""
    import file_archive_org_puzzles as archive
    rows, paths = [], {}
    for path in fetcher.puzzle_files():
        series, number = series_meta.parse_id(path.stem)
        if series != "ftcryptic":
            continue
        puzzle = fetcher.read_puzzle_file(path)
        rows.append((number, series_meta.puzzle_day(puzzle), (puzzle.get("source") or {}).get("url")))
        paths[number] = path
    found = misdated_ft(rows, lambda item: archive.dir_cache.listed(archive.CACHE / item))
    for n, _stored, fixed, _clash, _why in found:
        if fixed and apply_it:
            puzzle = fetcher.read_puzzle_file(paths[n])
            puzzle["date"] = fixed.isoformat()
            fetcher.write_puzzle_file(paths[n], puzzle)
    return found


def day(when):
    """A datetime.date as a readable day, for the report."""
    return "—" if when is None else when.isoformat()


def in_range(number, args):
    return ((args.start is None or number >= args.start)
            and (args.end is None or number <= args.end))


# Link words misfiled as letterless wordplay leaves. linkWords is derived (the
# clue words no span covers), so the repair is to take the leaf out of the tree.
PAD_NOTE = re.compile(r"^(?:the extra word, )?(?:surface padding|joins the|a joining word|joining word)",
                      re.I)
# A note that gives the leaf another job: a letter it supplies, a preamble
# rule, a cross-reference, an Azed meaning, a reference back.
PAD_BAD = re.compile(r"letter|preamble|theme|cross-ref|meaning|definition|indicator|superfluous"
                     r"|spare|refer|stands for|hidden|split|halves|removed", re.I)
LINK_WORDS = {"and", "with", "a", "an", "the", "on", "in", "to", "at", "of", "for", "by", "from",
              "is", "be", "as", "so", "or", "but", "then", "while", "when", "that", "which"}
PRONOUNS = {"it", "this", "he", "she", "they", "them", "her", "him", "his", "its", "their", "these",
            "those", "there's", "'ll"}
SKIPPED = collections.Counter()  # why a candidate was left alone, for the report


# A link word whose note says only what it does between the pieces: "joins the two
# sets of letters", "places the first piece before the second", "simply joins the
# pieces", "link joining rook to crow", "on places the betting term before the blow".
JOIN_NOTE = re.compile(r"^(?:\w+ )?(?:simply |just )?(?:joins?\b|joining\b|places?\b|placement\b|puts\b"
                       r"|link\b|surface link\b|a link\b)", re.I)
# What a joining note must not say: the leaf stands for letters that are taken out,
# a theme, a cross-reference, a meaning. "letters" alone is fine ("joins the two sets
# of letters"); the evaluator then confirms the answer survives the move.
JOIN_BAD = re.compile(r"preamble|theme|cross-ref|meaning|definition|indicator|superfluous|spare"
                      r"|refer|stands for|hidden|split|removed|\bout\b|\bremove", re.I)
# Words a setter uses to join pieces, beyond LINK_WORDS (wordplay.CONNECTIVE_WORDS in the validator).
JOIN_WORDS = LINK_WORDS | {"has", "having", "giving", "making", "gets", "get", "gives", "makes", "makes",
                           "after", "before", "next", "beside", "plus", "next to", "alongside", "over",
                           "under", "above", "below", "against", "into", "upon", "round", "about",
                           "puts", "put", "see", "seeing", "bearing", "taking", "takes", "holding"}
# "gives no letters", "adds no letters" say the leaf is padding; the bare word "letter"
# in PAD_BAD is what catches a leaf that supplies or loses one.
NO_LETTERS = re.compile(r"\b(?:gives?|adds?|supplies|has|contributes|giving|adding|with)\s+no\s+letters?\b", re.I)


def _padding_kind(leaf):
    """None when the leaf is not a candidate; 'ok' when it is a link word;
    otherwise the reason it is skipped."""
    if "op" in leaf or not leaf.get("unchecked") or not leaf.get("words") or leaf.get("gives"):
        return None
    words, note = leaf["words"].strip().lower(), leaf.get("note") or ""
    padded = bool(PAD_NOTE.match(note))
    joins = words in JOIN_WORDS and bool(JOIN_NOTE.match(note))
    if not padded and not joins and not (note == "" and words in LINK_WORDS):
        return "other note or word, not clearly padding"
    if joins:
        if JOIN_BAD.search(note):
            return "note gives it another job"
    elif PAD_BAD.search(NO_LETTERS.sub("", note)):
        return "note gives it another job"
    if words in PRONOUNS:
        return "pronoun, may refer back"
    if len(words.split()) > 4:
        return "long phrase, may be wordplay"
    if re.search(r"\d|\bacross\b|\bdown\b", words):
        return "placeholder or cross-reference"
    return "ok"


def unpad_charades(entry, puzzle):
    """Take padding leaves out of the charades of one entry's wordplay. Returns
    the words removed. Only a leaf the tree can lose without changing the
    answer: the tree is evaluated before and after, and the change is dropped
    if it differs."""
    ann = entry.get("annotation") or {}
    tree = ann.get("wordplay")
    if not isinstance(tree, dict):
        return []
    work = copy.deepcopy(tree)
    removed = []

    def go(node):
        dropped = False
        if node.get("op") == "charade":
            parts = node.get("parts") or []
            kinds = [_padding_kind(p) if isinstance(p, dict) else None for p in parts]
            keep = [p for p, k in zip(parts, kinds) if k != "ok"]
            SKIPPED.update(k for k in kinds if k and k != "ok")
            # A charade of one piece with nothing else of its own is that piece.
            # One with fields of its own, or whose piece is a bare leaf (the
            # validator then wants singleLeaf) or an unchecked step (arity),
            # needs a rewrite, not code: the leaf stays where it is.
            if len(keep) < len(parts) and len(keep) == 1 \
                    and (set(node) > {"op", "parts"} or "op" not in keep[0] or keep[0].get("unchecked")):
                SKIPPED["removal would leave a one-piece charade needing a rewrite"] += 1
            elif len(keep) < len(parts) and keep:
                removed.extend(p["words"] for p, k in zip(parts, kinds) if k == "ok")
                dropped = True
                node["parts"] = keep
        for i, p in enumerate(node.get("parts") or []):
            if isinstance(p, dict):
                node["parts"][i] = go(p)
        if dropped and len(node["parts"]) == 1:
            return node["parts"][0]
        return node

    work = go(work)
    if not removed:
        return []
    # Padding that is most of the clue is a themed or odd clue, not link words.
    clue_words = len((entry.get("clue") or {}).get("text", "").split())
    if len(removed) > 2 or sum(len(w.split()) for w in removed) * 2 > clue_words:
        SKIPPED["padding is most of the clue"] += len(removed)
        return []
    import annotation
    try:
        was = annotation.view(copy.deepcopy(ann), entry, puzzle)["answer"]
        now_ann = dict(ann, wordplay=work)
        now = annotation.view(now_ann, entry, puzzle)["answer"]
    except Exception:
        SKIPPED["tree no longer evaluates"] += len(removed)
        return []
    if was != now:
        SKIPPED["tree no longer evaluates"] += len(removed)
        return []
    ann["wordplay"] = work
    return removed


def repair(path, puzzle, apply_it, padding_only=False, learned=False, mends=False):
    """Repair one file. Returns the one-line report, or None if it was clean."""
    before = json.dumps(puzzle, sort_keys=True, ensure_ascii=False)
    fixed = copy.deepcopy(puzzle)

    notes = []
    if mends:
        # The full clue_repair.mend_text (less EXCLUDED_MENDS) on clue text alone,
        # on an archive.org filer's file: the rules written since the file was.
        if not read_by_archive_filer(fixed):
            return None
        if any("number" not in e or "direction" not in e for e in fixed.get("entries") or ()):
            return None
        found = []
        texts = mend_clue_text(fixed, skip=EXCLUDED_MENDS | ONLY_SKIP, log=found)
        if not texts:
            return None
        # A clue with a hand annotation moves its quoted phrases with the words
        # (enumeration.rewrite_entry); one whose phrase no longer sits in the new
        # text would lose its hand-made link, so that file is left as it is.
        for e in fixed["entries"]:
            note = e.get("annotation")
            if entry_id(e) in texts and isinstance(note, dict):
                for holder, key in enumeration._quoted_strings(e):
                    if holder[key] not in texts[entry_id(e)]:
                        return f"{path.stem}: left alone, annotation of {entry_id(e)} would lose its phrase {holder[key]!r}"
        MEND_LOG.extend(found)
        line = f"{path.stem}: {len(texts)} clue(s) mended: " + ", ".join(sorted(texts))
        if apply_it:
            import puzzle_integrity
            try:
                fetcher.write_puzzle_file(path, fixed)
            except puzzle_integrity.RefusedWrite as refused:
                return f"{path.stem}: left alone, the write was refused: {refused}"
        return line
    if learned:
        # Only the mends learned from the rereads (clue_repair.learned_mends), on
        # an archive.org filer's file: what a reread of the same file would
        # otherwise do by hand. No other repair, nor an older text rule.
        if not read_by_archive_filer(fixed):
            return None
        texts = mend_clue_text(fixed, learned_only=True)
        if not texts:
            return None
        line = f"{path.stem}: {len(texts)} clue(s) with a learned mend: " + ", ".join(sorted(texts))
        if apply_it:
            import puzzle_integrity
            try:
                fetcher.write_puzzle_file(path, fixed)
            except puzzle_integrity.RefusedWrite as refused:
                # A defect the mend did not make and cannot mend: the file stays as it is.
                return f"{path.stem}: left alone, the write was refused: {refused}"
        return line
    if padding_only:
        unpadded = [(entry_id(e), w) for e in fixed["entries"] for w in unpad_charades(e, fixed)]
        if not unpadded:
            return None
        if apply_it:
            fetcher.write_puzzle_file(path, fixed)
        return f"{path.stem}: link words taken out of the wordplay: " \
               + ", ".join(f"{eid} {w!r}" for eid, w in unpadded)
    letters = normalise_solutions(fixed)
    if letters:
        notes.append(f"{len(letters)} solution(s) normalised: "
                     + ", ".join(f"{was}→{now}" for _id, was, now in letters))
    masked = unmask_solutions(fixed)
    if masked:
        notes.append(f"masked ({', '.join(f'{eid} {sol}' for eid, sol in masked)})"
                     f" — all {len(fixed['entries'])} entries stored unsolved")
    # The group rules reason over every member's claim; the file keeps the
    # group on the leader alone. See tools/groups.py.
    kept = groups.off_start(fixed["entries"])
    groups.spread(fixed["entries"])
    broken = dissolve(fixed)
    if broken:
        notes.append(f"{len(broken)} false cross-reference(s) dissolved: "
                     + ", ".join(" + ".join(g) for g in broken))

    rebuilt = rebuild(fixed)
    if rebuilt:
        notes.append(f"{len(rebuilt)} linked answer(s) reassembled: "
                     + ", ".join(" + ".join(g) for g in rebuilt))
    groups.collapse(fixed["entries"], kept)

    unpadded = [(entry_id(e), w) for e in fixed["entries"] for w in unpad_charades(e, fixed)]
    if unpadded:
        notes.append("link words filed as wordplay leaves taken out: "
                     + ", ".join(f"{eid} {w!r}" for eid, w in unpadded))

    fixed, archive_notes = mechanical(fixed)
    notes += archive_notes

    if json.dumps(fixed, sort_keys=True, ensure_ascii=False) == before:
        return None
    if apply_it:
        # No generator argument: write_puzzle_file keeps the acquirer the file
        # already names, and a repair is not an acquisition.
        fetcher.write_puzzle_file(path, fixed)
    return f"{path.stem}: " + "; ".join(notes)


def git_out(*args):
    """The stdout of a git command run in the repo, or "" when it fails."""
    done = subprocess.run(["git", "-C", str(fetcher.ROOT), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def spoiled_commits(since, ref="origin/master"):
    """{puzzle id: [parent-side shas, newest first]} for each puzzle an
    "Update" commit on `ref` since `since` rewrote ("Update times-N", or a
    batched "Update N puzzles" naming its files)."""
    touched = {}
    log = git_out("log", f"--since={since}", "--format=@%H", "--name-only", "--grep=^Update ", ref)
    sha = None
    for line in log.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        elif line.endswith(".json") and sha and Path(line).stem.startswith("times-"):
            touched.setdefault(Path(line).stem, []).append((sha, line))
    return touched


def repair_spoiled_clues(since="2026-10-20", apply_it=False, ref="origin/master"):
    """[(id, light, was, now)] for each clue a reread of a times puzzle
    spoiled with the neighbouring print's words and this restores. For each
    puzzle an "Update times-" commit since `since` rewrote, each commit's
    parent copy is the held file and the current file the reading:
    file_archive_org_puzzles.keep_held_clues takes back each held clue the
    new text does not corrects() (a restored "a" or "and" does, so stays).
    Answers and all else stay the current file's. Only the touched puzzles
    are loaded."""
    import file_archive_org_puzzles as archive
    restored = []
    for pid, commits in sorted(spoiled_commits(since, ref).items()):
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        puzzle = fetcher.read_puzzle_file(path)
        done = set()
        for sha, rel in commits:
            try:
                old = json.loads(git_out("show", f"{sha}^:{rel}"))
            except ValueError:
                continue
            # keep_held_clues also takes back a held clue the reread fixed
            # ("enter tained"), so only the lights the reread grew words in
            # are taken from its copy.
            kept = copy.deepcopy(puzzle)
            lost = {entry_id(e): e for e in kept["entries"]}
            for lid in archive.keep_held_clues(kept, old):
                e = next(e for e in puzzle["entries"] if entry_id(e) == lid)
                was, now = (e.get("clue") or {}).get("text") or "", lost[lid]["clue"]["text"]
                if lid in done or not grown(now, was):
                    continue
                done.add(lid)
                e["clue"] = lost[lid]["clue"]
                if "annotation" in lost[lid]:
                    e["annotation"] = lost[lid]["annotation"]
                restored.append((pid, lid, was, now))
        if done and apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    return restored


def repair_regressed_clues(since="5 days ago", apply_it=False, ref="origin/master"):
    """[(id, light, was, now)] for each clue a reread of a times puzzle made
    worse and this restores from git history. Each "Update" commit on `ref`
    since `since` is compared clue by clue with its parent: where
    file_archive_org_puzzles.regressed says the new words lost the held
    ones' print (a lexicon word turned non-word, a word cut at its edge,
    "1st Earl" to "st Earl") and the file still reads the commit's words,
    the parent's clue (and annotation) comes back. Oldest commit first, so
    a chain of rereads ends on the last good words. Nothing else in the
    file changes; with `apply_it` False nothing is written."""
    import file_archive_org_puzzles as archive
    restored = []
    for pid, commits in sorted(spoiled_commits(since, ref).items()):
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        puzzle = fetcher.read_puzzle_file(path)
        now_by = {entry_id(e): e for e in puzzle["entries"]}
        changed = False
        for sha, rel in reversed(commits):
            try:
                before = json.loads(git_out("show", f"{sha}^:{rel}"))
                after = json.loads(git_out("show", f"{sha}:{rel}"))
            except ValueError:
                continue
            was_by = {entry_id(e): e for e in before["entries"]}
            for e in after["entries"]:
                lid = entry_id(e)
                h, cur = was_by.get(lid), now_by.get(lid)
                held, new = ((h or {}).get("clue") or {}), (e.get("clue") or {})
                if cur is None or not (held.get("text") or "").strip() or held.get("text") == new.get("text") \
                        or (cur.get("clue") or {}).get("text") != new.get("text") \
                        or held.get("enumeration") != new.get("enumeration") \
                        or not archive.regressed(held["text"], new.get("text") or "", new.get("asPrinted") or ()):
                    continue
                restored.append((pid, lid, new.get("text"), held["text"]))
                cur["clue"] = held
                if h.get("annotation"):
                    cur["annotation"] = h["annotation"]
                changed = True
        if changed and apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    return restored


def repair_lost_breaks(since="2026-10-21", apply_it=False, ref="origin/master"):
    """[(id, light, was, now)] (counts) for each clue whose count a reread of a
    times puzzle slipped and this restores from git history: each "Update"
    commit on `ref` since `since` is compared clue by clue with its parent,
    and where file_archive_org_puzzles.count_slipped says the new count
    traded word breaks the answer bears out for other breaks ("2,3,2,3,2"
    over ONTHEUPANDUP to "5,7", a neighbour's count) or is the grid's
    length over a held count with breaks, the words stand and the file
    still holds the commit's count, the parent's count and its marks come
    back. A lone count read off the print ("5,2" to "7") stays: it is the
    print's. Nothing else in the file changes; with `apply_it` False
    nothing is written."""
    import file_archive_org_puzzles as archive
    restored = []
    for pid, commits in sorted(spoiled_commits(since, ref).items()):
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        puzzle = fetcher.read_puzzle_file(path)
        now_by = {entry_id(e): e for e in puzzle["entries"]}
        changed = False
        for sha, rel in reversed(commits):
            try:
                before = json.loads(git_out("show", f"{sha}^:{rel}"))
                after = json.loads(git_out("show", f"{sha}:{rel}"))
            except ValueError:
                continue
            was_by = {entry_id(e): e for e in before["entries"]}
            for e in after["entries"]:
                lid = entry_id(e)
                h, cur = was_by.get(lid), now_by.get(lid)
                held, new = ((h or {}).get("clue") or {}), (e.get("clue") or {})
                if cur is None or not held.get("enumeration") or held.get("text") != new.get("text") \
                        or held.get("enumeration") == new.get("enumeration") \
                        or (cur.get("clue") or {}).get("enumeration") != new.get("enumeration") \
                        or not archive.count_slipped(held, new, cur.get("solution") or (h or {}).get("solution")):
                    continue
                restored.append((pid, lid, new.get("enumeration"), held["enumeration"]))
                cur["clue"] = archive.held_count(cur["clue"], held)
                changed = True
        if changed and apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    return restored


#: Answers-only rereads dropped every held answer they did not read again from here to 10-25
#: (file_archive_org_puzzles.decide: 312 Times files, 986 answers; times-7522 all 26).
LOST_ANSWERS_SINCE = "2026-10-22"


def repair_lost_answers(since=LOST_ANSWERS_SINCE, apply_it=False, ref="origin/master"):
    """([(id, light, answer, sha)] restored, [(id, light, answer, why)] left) for each Times answer
    an "Update" commit on `ref` since `since` blanked and this takes back from git history. A light
    is restored when the last commit to change it was such an "Update" blanking it (no later
    reread, repair or hand edit settled it otherwise), the current file leaves it blank, the old
    answer fills its light and fits every letter crossing it in the current file (and every other
    answer restored), and no misread rule names it (misread_word; MISREAD_NAMES). Its annotation
    comes back with it. Nothing else changes; with `apply_it` False nothing is written."""
    import file_archive_org_puzzles as archive
    named = {(p, lid) for p, lid, _w in MISREAD_NAMES}
    restored, left = [], []
    def cells(e):
        x, y, across = e["position"]["x"], e["position"]["y"], e["direction"] == "across"
        return [(x + i * across, y + i * (not across)) for i in range(e["length"])]
    # Every commit since `since` touching a Times file, one log pass; blobs through one cat-file.
    touched, sha, subject = {}, None, ""
    for line in git_out("log", f"--since={since}", "--format=@%H %s", "--name-only", ref, "--", "puzzles/times").splitlines():
        if line.startswith("@"):
            sha, _, subject = line[1:].partition(" ")
        elif line.endswith(".json") and sha:
            touched.setdefault(line, []).append((sha, subject))
    cat = subprocess.Popen(["git", "-C", str(fetcher.ROOT), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    def entries(spec):
        cat.stdin.write((spec + "\n").encode())
        cat.stdin.flush()
        head = cat.stdout.readline().split()
        if len(head) < 3 or head[1] == b"missing":
            return {}
        data = cat.stdout.read(int(head[2]))
        cat.stdout.read(1)
        try:
            return {entry_id(e): e for e in json.loads(data)["entries"]}
        except (ValueError, KeyError):
            return {}
    for rel, log in sorted(touched.items()):
        pid = Path(rel).stem
        if not pid.startswith("times-") or not any(s.startswith("Update") for _h, s in log):
            continue
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        last = {}  # light: (sha, subject, entry before, entry after) of the newest commit changing its answer
        before = entries(f"{log[-1][0]}^:{rel}")
        for sha, subject in reversed(log):
            after = entries(f"{sha}:{rel}")
            for lid in set(before) | set(after):
                was, now = (before.get(lid) or {}).get("solution"), (after.get(lid) or {}).get("solution")
                if (was or None) != (now or None):
                    last[lid] = (sha, subject, before.get(lid) or {}, now)
            before = after
        puzzle = fetcher.read_puzzle_file(path)
        if "blog" in (puzzle.get("solutions") or {}):
            continue
        letters = {rc: ch for e in puzzle["entries"] if e.get("solution") for rc, ch in zip(cells(e), e["solution"])}
        changed = False
        for e in puzzle["entries"]:
            lid = entry_id(e)
            sha, subject, held, now = last.get(lid) or (None, "", {}, None)
            word = held.get("solution")
            if not subject.startswith("Update") or not word or now or e.get("solution"):
                continue
            why = ("its light's length" if len(word) != e["length"]
                   else "named a misread" if (pid, lid) in named
                   or archive.misread_word(word, (e.get("clue") or {}).get("enumeration"))
                   else "a crossing letter" if any(letters.get(rc, ch) != ch for rc, ch in zip(cells(e), word)) else None)
            if why:
                left.append((pid, lid, word, why))
                continue
            e["solution"] = word
            if held.get("annotation") and not e.get("annotation"):
                e["annotation"] = held["annotation"]
            letters.update(zip(cells(e), word))
            restored.append((pid, lid, word, sha[:11]))
            changed = True
        if changed and apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    cat.stdin.close()
    cat.wait()
    return restored, left


#: (puzzle id, light, answer filed) for Times answers a solution-grid read filed since the
#: classifier's 50-to-1 decode (2026-10-22) that are a surname cmudict alone lists, misread
#: off a word one or two letters away (TROEGER for TRIGGER, the case trove_solution_ocr.name_only
#: now stops): each was judged against its clue, of the 437 such answers filed then (the rest
#: names the clue bears out: NORGE, SCHEER, COSIMA).
MISREAD_NAMES = (
    ("times-4666", "4-down", "BOAN"), ("times-4747", "24-down", "LEONI"), ("times-5136", "1-across", "CALES"),
    ("times-5640", "21-down", "BARTLE"), ("times-5771", "22-down", "BRESSER"), ("times-6453", "3-down", "BASWELL"),
    ("times-6849", "13-across", "BUCHE"), ("times-14430", "6-down", "BUCHE"),
    ("times-9443", "5-down", "UNDERTHETAGLE"), ("times-11756", "10-across", "ARANA"),
    ("times-12814", "26-across", "ARANA"), ("times-10958", "26-down", "BEEL"), ("times-11020", "13-across", "FLAD"),
    ("times-11770", "9-across", "PINEDO"), ("times-12325", "13-across", "GAUDET"), ("times-13353", "25-across", "BEALS"),
    ("times-13595", "20-down", "FRISKE"), ("times-13817", "1-across", "MASTERCABO"), ("times-14160", "4-down", "GARR"),
    ("times-14336", "20-down", "BESSERT"), ("times-14780", "24-down", "HORD"), ("times-14999", "16-across", "ALDA"),
    ("times-16123", "25-down", "TONIA"), ("times-16577", "23-across", "HAGE"), ("times-16627", "10-across", "RABEL"),
    ("times-16997", "22-down", "RISA"), ("times-22232", "28-across", "STAI"), ("times-5671", "4-down", "ELSTON"),
    ("times-10098", "27-across", "ASBRIDGE"), ("times-22707", "9-across", "ORMAND"),
)


def repair_misread_names(apply_it=False, rows=MISREAD_NAMES):
    """[(id, light, answer)] for each of `rows` whose file still holds that answer: the answer is
    blanked (a light left for a reread to fill, not a wrong word). Nothing else in the file
    changes; with `apply_it` False nothing is written."""
    blanked = []
    by_pid = {}
    for pid, lid, word in rows:
        by_pid.setdefault(pid, []).append((lid, word))
    for pid, lights in sorted(by_pid.items()):
        path = puzzle_paths.find(pid)
        if path is None:
            continue
        puzzle = fetcher.read_puzzle_file(path)
        changed = False
        for e in puzzle["entries"]:
            for lid, word in lights:
                if entry_id(e) == lid and e.get("solution") == word:
                    e["solution"] = None
                    blanked.append((pid, lid, word))
                    changed = True
        if changed and apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    return blanked


#: The day from which repair_uncrossed looks at the answers filed to Times files: 8,564's BATES for
#: PATES ("They're made of paste") was filed 10-18.
UNCROSSED_SINCE = "2026-10-18"
#: How many days after a puzzle's own date its solution grid's crop may be dated (the host edition).
CROP_DAYS = 14


def answered_since(since=UNCROSSED_SINCE, ref="HEAD"):
    """{puzzle id: {light: answer}} of the Times answers `ref`'s files hold that the last commit
    before `since` did not (a file new since then gives every answer it holds)."""
    base = git_out("rev-list", "-1", f"--before={since}T00:00", ref).strip()
    if not base:
        return {}
    got = {}
    for rel in git_out("diff", "--name-only", base, ref, "--", "puzzles/times").split():
        if not rel.endswith(".json") or not (fetcher.ROOT / rel).exists():
            continue
        now = json.loads((fetcher.ROOT / rel).read_text())
        try:
            was = json.loads(git_out("show", f"{base}:{rel}") or "{}")
        except ValueError:
            was = {}
        held = {entry_id(e): e.get("solution") for e in was.get("entries") or ()}
        new = {entry_id(e): e["solution"] for e in now.get("entries") or ()
               if e.get("solution") and not held.get(entry_id(e))}
        if new:
            got[Path(rel).stem] = new
    return got


def grid_crops(root=None):
    """{puzzle number: [(date, path)]} of the solution grid crops file_archive_org_puzzles.read_solution
    leaves (CROPS/solutions/<edition>_<number>.png)."""
    import file_archive_org_puzzles as archive
    by = {}
    for p in Path(root or archive.CROPS / "solutions").glob("*.png"):
        num = p.stem.rsplit("_", 1)[-1]
        try:
            day = datetime.strptime(p.stem[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if num.isdigit():
            by.setdefault(int(num), []).append((day, p))
    return by


def grid_crop(puzzle, crops):
    """The earliest crop of `crops` (grid_crops) for `puzzle`'s number dated from its own date
    to CROP_DAYS after, or None."""
    try:
        day = datetime.strptime(puzzle.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        return None
    near = sorted(c for c in crops.get(puzzle.get("number"), ()) if 0 <= (c[0] - day).days <= CROP_DAYS)
    return near[0][1] if near else None


def misread_alternative(word, lone):
    """Whether one letter's change at a lone cell (`lone`: the letters' indices) of `word` makes a
    listed word: a misread there has a word to have been (BATES for PATES)."""
    import trove_solution_ocr as tso
    return any(i in lone for i, _ in tso.one_change(word.upper()))


def uncrossed_suspects(puzzle, lights=None):
    """{light: [lone letter indices]} of `puzzle`'s answers (those of `lights`, all by default)
    file_archive_org_puzzles.uncrossed leaves out, short of the classifier's reading of its cells,
    where a misread_alternative lies. The rest it leaves out (a word no change at its lone letters
    makes another listed word) are not looked at: their crop's classifier read costs ~5 s a puzzle."""
    import file_archive_org_puzzles as archive
    import trove_solution_ocr as tso
    es = puzzle.get("entries") or ()
    answers = {entry_id(e): e["solution"] for e in es if e.get("solution")}
    if not answers:
        return {}
    grid = tso.puzzle_grid(puzzle)
    enums = {(e["number"], e["direction"]): (e.get("clue") or {}).get("enumeration") for e in es}
    lts = tso.lights(grid)
    on = {}
    for (n, dr), cells in lts.items():
        for rc in cells:
            on.setdefault(rc, []).append(f"{n}-{dr}")
    out = {}
    for k in sorted(archive.uncrossed(answers, grid, enums)):
        if lights is not None and k not in lights:
            continue
        idx = [i for i, _, _ in archive.lone_cells(k, lts, on, answers)]
        if misread_alternative(answers[k], idx):
            out[k] = idx
    return out


#: grid_crops() for the workers of uncrossed_reads (forked: read once, not sent with each puzzle).
_CROPS = {}


def crop_probs(crop, grid):
    """trove_solution_ocr.cell_probs of `crop` for `grid`, kept under CROPS/cell_probs by the crop's
    size and time and the grid, so a dry run's reads serve the --apply that follows."""
    import hashlib
    import numpy as np
    import file_archive_org_puzzles as archive
    import trove_solution_ocr as tso
    st = Path(crop).stat()
    key = hashlib.sha256(json.dumps([str(crop), st.st_size, st.st_mtime_ns, ["".join(r) for r in grid]]).encode()).hexdigest()[:20]
    kept = archive.CROPS / "cell_probs" / f"{key}.npz"
    if kept.exists():
        with np.load(kept) as z:
            return None if not len(z["cells"]) else {tuple(int(v) for v in rc): p for rc, p in zip(z["cells"], z["p"])}
    probs = tso.cell_probs(crop, grid)
    kept.parent.mkdir(parents=True, exist_ok=True)
    cells = sorted(probs or ())
    tmp = kept.with_suffix(".part.npz")
    np.savez(tmp, cells=np.array(cells, dtype=np.int16).reshape(-1, 2),
             p=np.array([probs[rc] for rc in cells], dtype=np.float32).reshape(-1, 26))
    tmp.replace(kept)
    return probs


def _uncrossed_one(item):
    """(id, [(light, answer, lowest lone-cell probability or None: no crop read, rival)]) of one
    puzzle's uncrossed_suspects, `rival` the listed word the classifier reads its lone letters as
    (file_archive_org_puzzles.misread_rival), None where it stands."""
    pid, lights = item
    import file_archive_org_puzzles as archive
    import trove_solution_ocr as tso
    path = puzzle_paths.find(pid)
    if path is None:
        return pid, []
    puzzle = fetcher.read_puzzle_file(path)
    # A blog's write-up keys the file (merge_answers' _fill_writeup_blanks): its answers a person typed.
    if (puzzle.get("source") or {}).get("acquiredBy") != archive.TOOL or "blog" in (puzzle.get("solutions") or {}):
        return pid, []
    sus = uncrossed_suspects(puzzle, lights)
    if not sus:
        return pid, []
    grid = tso.puzzle_grid(puzzle)
    crop = grid_crop(puzzle, _CROPS)
    probs = crop_probs(crop, grid) if crop else None
    es = puzzle["entries"]
    answers = {entry_id(e): e["solution"] for e in es if e.get("solution")}
    lts = tso.lights(grid)
    on = {}
    for (n, dr), cells in lts.items():
        for rc in cells:
            on.setdefault(rc, []).append(f"{n}-{dr}")
    got = []
    for k in sus:
        lone = archive.lone_cells(k, lts, on, answers)
        low = None if not probs else round(min((float(probs[rc][tso.AZ.index(ch)]) if rc in probs and ch in tso.AZ
                                                else 0.0 for _, rc, ch in lone), default=1.0), 3)
        got.append((k, answers[k], low, archive.misread_rival(answers[k], lone, probs) if probs else None))
    return pid, got


def uncrossed_reads(answered, workers=1, crops=None):
    """[(id, light, answer, lowest lone-cell probability, rival)] of _uncrossed_one over
    `answered` ({id: lights}, answered_since)."""
    _CROPS.clear()
    _CROPS.update(grid_crops() if crops is None else crops)
    items = [(pid, set(lights)) for pid, lights in sorted(answered.items())]
    found = []
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(workers) if workers > 1 else contextlib.nullcontext() as pool:
        for i, got in enumerate(pool.imap(_uncrossed_one, items, chunksize=4) if pool else map(_uncrossed_one, items)):
            found.append(got)
            if i % 500 == 499:
                print(f"{i + 1} of {len(items)} puzzles read", file=sys.stderr, flush=True)
    return [(pid, k, a, low, rival) for pid, rows in found for k, a, low, rival in rows]


def repair_uncrossed(since=UNCROSSED_SINCE, apply_it=False, workers=1, answered=None, crops=None):
    """[(id, light, answer, the listed word the classifier reads it as)] for each Times answer filed
    since `since` (answered_since) that file_archive_org_puzzles.uncrossed leaves out by the
    classifier's reading of the grid's crop (cell_probs): a lone letter (unchecked, or crossed by a
    blank light) read as another at RIVAL_P and over its own, making a listed word (misread_rival).
    Each is blanked, a light left for a reread to fill, not a wrong word (8,564's BATES for PATES,
    its B read .035); an answer whose crop is not read stands. One pass over the files as they
    stand: a blank made here leaves no other answer out. With `apply_it` False nothing is written."""
    answered = answered_since(since) if answered is None else answered
    bad = {}
    for pid, k, a, low, rival in uncrossed_reads(answered, workers, crops):
        if rival:
            bad.setdefault(pid, []).append((k, a, rival))
    blanked = []
    for pid, rows in sorted(bad.items()):
        path = puzzle_paths.find(pid)
        puzzle = fetcher.read_puzzle_file(path)
        drop = {k: a for k, a, _ in rows}
        for e in puzzle["entries"]:
            if drop.get(entry_id(e)) and e.get("solution") == drop[entry_id(e)]:
                e["solution"] = None
                e.pop("annotation", None)
        blanked += [(pid, k, a, rival) for k, a, rival in rows]
        if apply_it:
            fetcher.write_puzzle_file(path, puzzle)
    return blanked


#: How many days on an edition's next issue may lie (a Sunday, a holiday, a missing paper).
NEXT_ISSUE_DAYS = 4


def misnumbered_titles(titles, headings, held):
    """[(number, day, title, why)], newest first, of the puzzles `held` ({number: date})
    filed one below the title their own page prints: `titles` ({date: [title numbers]}
    of each edition) reads No `title` = `number` + 1 alone on `day` and not `number`,
    and a solution heading bears the title out (`headings`, {date: [numbers]}): the
    page's own of the issue before (`number`) or, on a Saturday, of the Saturday
    before's prize (`title` - 6), or the next issue's of the title. The
    filer's count of issues from a neighbour filed a number off once overruled such
    titles (file_archive_org_puzzles.placed: vouched). `why` is None for one to
    renumber to `title`: its title free, or freed by one renumbered before it (newest
    first); "duplicate" when the title is the same day's other file (one page filed
    twice); else what holds the title."""
    days = sorted(titles)
    moving, out = set(), []
    for number, day in sorted(held.items(), reverse=True):
        title = number + 1
        if titles.get(day) != [title]:
            continue
        k = bisect.bisect_right(days, day)
        later = days[k] if k < len(days) and (days[k] - day).days <= NEXT_ISSUE_DAYS else None
        own = headings.get(day, ())
        if number not in own and not (day.weekday() == 5 and title - 6 in own) \
                and (later is None or title not in headings.get(later, ())):
            continue
        if title in held and title not in moving:
            why = "duplicate" if held[title] == day else f"No {title} is filed for {held[title]}"
        else:
            why = None
            moving.add(number)
        out.append((number, day, title, why))
    return out


def renumber_file(path, puzzle, number, apply_it=False):
    """The path puzzle file `path` (holding `puzzle`) moves to as No `number`: its id and number
    set, written beside it (the same day, so the same year folder) in the corpus's own form, the
    old file removed, and its generated puzzles/<id>.js shim (and .gz) replaced by the new id's
    when one was built. Nothing is written without `apply_it`."""
    series, _ = series_meta.parse_id(puzzle["id"])
    pid = f"{series}-{number}"
    dest = path.with_name(f"{pid}.json")
    if not apply_it:
        return dest
    moved = dict(puzzle, id=pid, number=number)
    fetcher.write_whole(dest, json.dumps(moved, indent=1, ensure_ascii=False) + "\n")
    path.unlink()
    shim = puzzle_paths.shim_path(path)
    if shim.exists():
        fetcher.write_shim(dest, moved)
    for old in (shim, shim.with_name(shim.name + ".gz")):
        if old.exists():
            old.unlink()
    return dest


def times_title_reads():
    """({date: [title numbers]}, {date: [solution heading numbers]}) of every Times
    edition's last ledger row whose page is one day's paper (a Gale page,
    file_archive_org_puzzles.ONE_DAY_ITEM): an archive.org item binds the next days'
    papers too (NewsUK 1981-03-05 holds 15465 and the 6th's 15466), so its scan's
    date is not each title's day."""
    import file_archive_org_puzzles as archive
    from datetime import date
    titles, headings = {}, {}
    for paper in (archive.GALE, archive.TIMES):
        for edition, row in archive.load_known(archive.ledger_of(paper=paper)).items():
            scan = row.get("scan") or {}
            if not scan.get("date") or archive.paper_of(edition).series != "times" \
                    or not archive.ONE_DAY_ITEM.match(edition.split("/")[0]):
                continue
            day = date.fromisoformat(scan["date"])
            titles.setdefault(day, []).extend(p["number"] for p in scan.get("puzzles", ()) if "fromSolutions" not in p)
            headings.setdefault(day, []).extend(s["number"] for s in scan.get("solutions", ()))
    return {d: sorted(set(t)) for d, t in titles.items()}, headings


def repair_renumbered(apply_it=False, reads=None, held=None):
    """misnumbered_titles over the Times puzzles held one below a title read (`reads`:
    times_title_reads(); `held`: {number: date}, the filer's held_dates), only the files
    it names read; each free one is renamed to its title, newest first, so none lands on
    another (renumber_file), and a duplicate's misnumbered copy is removed when it is the
    same page as the title's file. [(number, day, title, why)]; nothing is written
    without `apply_it`."""
    if held is None:
        import file_archive_org_puzzles as archive
        held = dict(archive.held_dates("times"))
    titles, headings = reads or times_title_reads()
    found = misnumbered_titles(titles, headings, held)
    load = lambda n: (lambda p: (p, fetcher.read_puzzle_file(p)))(puzzle_paths.find(f"times-{n}"))
    for number, _day, title, why in found:
        path, puzzle = load(number)
        if why is None:
            renumber_file(path, puzzle, title, apply_it)
        elif why == "duplicate" and apply_it \
                and (puzzle.get("source") or {}).get("url") == (load(title)[1].get("source") or {}).get("url"):
            path.unlink()
    return found


def grown(held, now):
    """Whether the clue text `now` is the held `held` with a few words added
    and none lost: a reread laying neighbouring print in a clue. A run of
    four words or more is the rest of a clue the held copy cut short."""
    words = lambda text: re.findall(r"\w+(?:'\w+)?", text.lower())
    held_w, now_w = words(held), words(now)
    it = iter(now_w)
    if len(now_w) <= len(held_w) or not all(w in it for w in held_w):
        return False
    runs = SequenceMatcher(None, held_w, now_w, autojunk=False).get_opcodes()
    return all(j2 - j1 < 4 for op, _i1, _i2, j1, j2 in runs if op == "insert")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spoiled-clues", nargs="?", const="2026-10-20", metavar="SINCE",
                    help="only restore the held clue of each times puzzle an 'Update times-' commit since SINCE "
                         "(default 2026-10-20) spoiled with a reread's neighbouring words; --apply writes")
    ap.add_argument("--regressed-clues", nargs="?", const="5 days ago", metavar="SINCE",
                    help="only restore, from git history, the held clue of each times puzzle an 'Update' commit "
                         "since SINCE (default '5 days ago') made worse: a word cut or turned non-word "
                         "(file_archive_org_puzzles.regressed); --apply writes")
    ap.add_argument("--lost-breaks", nargs="?", const="2026-10-21", metavar="SINCE",
                    help="only restore, from git history, the held count of each times puzzle an 'Update' commit "
                         "since SINCE (default 2026-10-21) slipped: word breaks the answer bears out traded for "
                         "a neighbour's, or the grid's length over them "
                         "(file_archive_org_puzzles.count_slipped); --apply writes")
    ap.add_argument("--lost-answers", nargs="?", const=LOST_ANSWERS_SINCE, metavar="SINCE",
                    help="only restore, from git history, each Times answer an 'Update' commit since SINCE "
                         "(default " + LOST_ANSWERS_SINCE + ") blanked, an answers-only reread dropping held "
                         "answers it did not read again, where it fits every crossing (repair_lost_answers); "
                         "--apply writes")
    ap.add_argument("--ft-dates", action="store_true",
                    help="only list the ftcryptic files dated on a Sunday, another number's day or out of "
                         "number order (misdated_ft), with the day their numbered neighbours settle; "
                         "--apply writes those")
    ap.add_argument("--misread-names", action="store_true",
                    help="only blank the Times answers in MISREAD_NAMES (a surname cmudict alone lists, "
                         "misread off a word: BOAN for ROAN); --apply writes")
    ap.add_argument("--uncrossed", nargs="?", const=UNCROSSED_SINCE, metavar="SINCE",
                    help="only blank the Times answers filed since SINCE (default " + UNCROSSED_SINCE + ") "
                         "with a letter no other answer checks that the cell classifier reads, off the grid's "
                         "crop, as another making a listed word (repair_uncrossed: BATES for PATES); "
                         "--apply writes")
    ap.add_argument("--workers", type=int, default=1, metavar="N",
                    help="with --uncrossed, classify the grid crops in N processes")
    ap.add_argument("--renumbered", action="store_true",
                    help="only rename the Times puzzles filed one below the title their page prints, "
                         "a solution heading bearing the title out (misnumbered_titles), newest first; "
                         "--apply writes")
    ap.add_argument("--apply", action="store_true",
                    help="write the repairs; without it nothing is written")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only, which is what happens anyway")
    ap.add_argument("--padding-only", action="store_true",
                    help="only take link words out of the wordplay; no other repair")
    ap.add_argument("--learned", action="store_true",
                    help="only the clue-text mends learned from the rereads (clue_repair.learned_mends: "
                         "stray underscore, figure speck, specked count, word stub) of archive.org "
                         "filers' files; no group, solution, padding or older text repair")
    ap.add_argument("--mends", action="store_true",
                    help="the full clue_repair.mend_text (less EXCLUDED_MENDS) on the clue text of archive.org "
                         "filers' files, for files written before its rules existed; no other repair. "
                         "Prints the changes per rule. --samples N shows N random diffs")
    ap.add_argument("--only", nargs="+", metavar="RULE",
                    help="with --mends, run only these clue_repair.mend_steps rules (e.g. stray_ampersand), "
                         "so a new rule's sweep makes no other rule's changes")
    ap.add_argument("--samples", type=int, default=0, metavar="N",
                    help="with --mends, print N random before/after clue texts")
    ap.add_argument("--series", help="one series key: cryptic, quiptic, everyman…")
    ap.add_argument("--from", dest="start", type=int,
                    help="lowest puzzle number to consider")
    ap.add_argument("--to", dest="end", type=int,
                    help="highest puzzle number to consider")
    ap.add_argument("--write-flags", nargs="?", const=str(FLAGS), metavar="PATH",
                    help="write the archive.org files whose word breaks only the print can give "
                         f"(default {FLAGS}): the queue reads those again, and no others for them")
    ap.add_argument("--write-breaks", action="store_true",
                    help=f"rebuild {fetcher.BREAKS} (the word breaks other puzzles print for an answer) and stop")
    args = ap.parse_args(argv)
    if args.write_breaks:
        settled, mixed = write_breaks()
        print(f"{settled} answers with settled word breaks, {mixed} printed both ways -> {fetcher.BREAKS}")
        return 0
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run say opposite things; pass one")
    if args.ft_dates:
        found = repair_ft_dates(args.apply)
        for n, stored, fixed, clash, why in found:
            print(f"ftcryptic-{n}: dated {stored} ({clash}) -> "
                  + (f"{fixed}" if fixed else f"left: {why}"))
        fixed = sum(1 for r in found if r[2])
        print(f"{len(found)} misdated, {fixed} {'redated' if args.apply else 'would be redated'}, "
              f"{len(found) - fixed} left to look at")
        return 0
    if args.renumbered:
        found = repair_renumbered(args.apply)
        for number, when, title, why in found:
            print(f"times-{number} ({when}): titled No {title} -> " + (f"times-{title}" if why is None else f"left: {why}"))
        moved = [r for r in found if r[3] is None]
        print(f"{len(found)} filed below their title, {len(moved)} {'renamed' if args.apply else 'would be renamed'}"
              + "".join(f", {decade}s {n}" for decade, n in sorted(Counter(r[1].year // 10 * 10 for r in moved).items())))
        return 0
    if args.uncrossed:
        blanked = repair_uncrossed(args.uncrossed, args.apply, args.workers)
        for pid, lid, word, rival in blanked:
            print(f"{pid} {lid}: {word} -> blank (the classifier reads {rival})")
        print(f"{len({r[0] for r in blanked})} puzzle(s), {len(blanked)} answer(s) "
              f"{'blanked' if args.apply else 'would be blanked'}")
        return 0
    if args.misread_names:
        blanked = repair_misread_names(args.apply)
        for pid, lid, word in blanked:
            print(f"{pid} {lid}: {word} -> blank")
        print(f"{len({r[0] for r in blanked})} puzzle(s), {len(blanked)} answer(s) "
              f"{'blanked' if args.apply else 'would be blanked'} of {len(MISREAD_NAMES)} listed")
        return 0
    if args.lost_answers:
        restored, left = repair_lost_answers(args.lost_answers, args.apply)
        for pid, lid, word, sha in restored:
            print(f"{pid} {lid}: blank -> {word} (blanked by {sha})")
        for pid, lid, word, why in left:
            print(f"{pid} {lid}: {word} left blank: {why}")
        print(f"{len({r[0] for r in restored})} puzzle(s), {len(restored)} answer(s) "
              f"{'restored' if args.apply else 'would be restored'}; {len(left)} left blank "
              + ", ".join(f"{why} {n}" for why, n in sorted(Counter(r[3] for r in left).items())))
        return 0
    if args.lost_breaks:
        restored = repair_lost_breaks(args.lost_breaks, args.apply)
        for pid, lid, was, now in restored:
            print(f"{pid} {lid}: {was!r} -> {now!r}")
        print(f"{len({r[0] for r in restored})} puzzle(s), {len(restored)} count(s) "
              f"{'restored' if args.apply else 'would be restored'}")
        return 0
    if args.regressed_clues:
        restored = repair_regressed_clues(args.regressed_clues, args.apply)
        for pid, lid, was, now in restored:
            print(f"{pid} {lid}: {was!r} -> {now!r}")
        print(f"{len({r[0] for r in restored})} puzzle(s), {len(restored)} clue(s) "
              f"{'restored' if args.apply else 'would be restored'}")
        return 0
    if args.spoiled_clues:
        restored = repair_spoiled_clues(args.spoiled_clues, args.apply)
        for pid, lid, was, now in restored:
            print(f"{pid} {lid}: {was!r} -> {now!r}")
        print(f"{len({r[0] for r in restored})} puzzle(s), {len(restored)} clue(s) "
              f"{'restored' if args.apply else 'would be restored'}")
        return 0
    if args.only:
        import clue_repair
        is_word, uses = clue_repair.lexicon()
        names = [n for n, _t in clue_repair.mend_steps("", is_word=is_word, uses=uses)]
        if not args.mends or set(args.only) - set(names):
            ap.error("--only takes --mends and rules of " + ", ".join(names))
        global ONLY_SKIP
        ONLY_SKIP = frozenset(names) - set(args.only)
    if args.series and args.series not in series_meta.SERIES:
        ap.error(f"no series {args.series!r} — " + ", ".join(sorted(series_meta.SERIES)))

    # One read per file. Dates are judged against a WHOLE series, so the
    # neighbours of a selected puzzle are collected even when the number range
    # excludes them — a range of ten puzzles cannot say which of the ten is out
    # of line. Only the selected ones are repaired, and only they are reported.
    examined, repaired, by_series, wanted, unsettled = 0, 0, {}, set(), []
    for path in fetcher.puzzle_files():
        series, number = series_meta.parse_id(path.stem)
        if args.series and series != args.series:
            continue
        puzzle = fetcher.read_puzzle_file(path)
        # A book's numbers are this repo's registry order, not a publication
        # sequence, so there is no run of dates for them to climb with.
        if not series_meta.is_book(series):
            by_series.setdefault(series, []).append((number, series_meta.puzzle_day(puzzle)))
        if not in_range(number, args):
            continue
        examined += 1
        wanted.add(path.stem)
        if args.write_flags and read_by_archive_filer(puzzle):
            unsettled.extend(puzzle["id"] for _ in flagged_word_breaks(puzzle)[:1])
        line = repair(path, puzzle, args.apply, args.padding_only, args.learned, args.mends)
        if line:
            repaired += 1
            print(line)

    if args.mends:
        for rule, n in sorted(Counter(r for _p, _l, r, _w, _n in MEND_LOG).items()):
            print(f"rule {rule}: {n} clue(s)")
        import random
        for pid, lid, rule, was, now in random.Random(1).sample(MEND_LOG, min(args.samples, len(MEND_LOG))):
            print(f"SAMPLE {pid} {lid} [{rule}]\n   - {was}\n   + {now}")
        by_series, wanted = {}, set()  # a mends run says nothing of dates

    misfiled = 0
    for series, dated in sorted(by_series.items()):
        for number, (stored, earliest, latest) in sorted(misfiled_dates(dated).items()):
            pid = series_meta.puzzle_id(series, number)
            if pid not in wanted:
                continue
            misfiled += 1
            # The lowest and highest puzzle of a series have a neighbour on one
            # side only, and "between — and 2015-07-25" is not a sentence.
            if earliest is None:
                window = f"no later than {day(latest)}"
            elif latest is None:
                window = f"no earlier than {day(earliest)}"
            else:
                window = f"between {day(earliest)} and {day(latest)}"
            print(f"{pid}: dated {day(stored)}, but its neighbours put it "
                  f"{window} — mis-filed, re-fetch it")

    for why, count in sorted(SKIPPED.items()):
        print(f"padding-like leaf left alone ({why}): {count}")
    if args.write_flags:
        write_flags(args.write_flags, unsettled)
        print(f"{len(unsettled)} archive.org file(s) hold a word-break count the lexicon cannot settle "
              f"-> {args.write_flags}")
    verb = "repaired" if args.apply else "would repair"
    print(f"{examined} file(s) examined, {verb} {repaired}, "
          f"{misfiled} mis-filed date(s) to re-fetch by hand")
    if repaired and not args.apply:
        print("nothing was written — pass --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
