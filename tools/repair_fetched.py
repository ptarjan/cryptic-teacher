#!/usr/bin/env python3
"""Repair puzzle files that were written before the fetcher learned better.

    python3 tools/repair_fetched.py                          # say what is wrong, change nothing
    python3 tools/repair_fetched.py --apply                   # write the repairs
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
import copy
import re
import json
import sys
from datetime import timedelta

import fetch_puzzle as fetcher  # the rules being applied live there
import groups
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


def _padding_kind(leaf):
    """None when the leaf is not a candidate; 'ok' when it is a link word;
    otherwise the reason it is skipped."""
    if "op" in leaf or not leaf.get("unchecked") or not leaf.get("words") or leaf.get("gives"):
        return None
    words, note = leaf["words"].strip().lower(), leaf.get("note") or ""
    padded = bool(PAD_NOTE.match(note))
    if not padded and not (note == "" and words in LINK_WORDS):
        return "other note or word, not clearly padding"
    if PAD_BAD.search(note):
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


def repair(path, puzzle, apply_it, padding_only=False):
    """Repair one file. Returns the one-line report, or None if it was clean."""
    before = json.dumps(puzzle, sort_keys=True, ensure_ascii=False)
    fixed = copy.deepcopy(puzzle)

    notes = []
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

    if json.dumps(fixed, sort_keys=True, ensure_ascii=False) == before:
        return None
    if apply_it:
        # No generator argument: write_puzzle_file keeps the acquirer the file
        # already names, and a repair is not an acquisition.
        fetcher.write_puzzle_file(path, fixed)
    return f"{path.stem}: " + "; ".join(notes)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the repairs; without it nothing is written")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only, which is what happens anyway")
    ap.add_argument("--padding-only", action="store_true",
                    help="only take link words out of the wordplay; no other repair")
    ap.add_argument("--series", help="one series key: cryptic, quiptic, everyman…")
    ap.add_argument("--from", dest="start", type=int,
                    help="lowest puzzle number to consider")
    ap.add_argument("--to", dest="end", type=int,
                    help="highest puzzle number to consider")
    args = ap.parse_args(argv)
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run say opposite things; pass one")
    if args.series and args.series not in series_meta.SERIES:
        ap.error(f"no series {args.series!r} — " + ", ".join(sorted(series_meta.SERIES)))

    # One read per file. Dates are judged against a WHOLE series, so the
    # neighbours of a selected puzzle are collected even when the number range
    # excludes them — a range of ten puzzles cannot say which of the ten is out
    # of line. Only the selected ones are repaired, and only they are reported.
    examined, repaired, by_series, wanted = 0, 0, {}, set()
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
        line = repair(path, puzzle, args.apply, args.padding_only)
        if line:
            repaired += 1
            print(line)

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
    verb = "repaired" if args.apply else "would repair"
    print(f"{examined} file(s) examined, {verb} {repaired}, "
          f"{misfiled} mis-filed date(s) to re-fetch by hand")
    if repaired and not args.apply:
        print("nothing was written — pass --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
