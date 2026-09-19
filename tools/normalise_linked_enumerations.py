#!/usr/bin/env python3
"""Put a solve record's linked answers into the corpus's leader form.

    python3 tools/normalise_linked_enumerations.py /tmp/penguin_solve_book18.json
    python3 tools/normalise_linked_enumerations.py /tmp/penguin_solve_*.json --check

An answer that spans two lights is stored ONE way here: the leader carries the
enumeration of the WHOLE answer and every continuation carries null.
puzzles/book-3003.js is the settled example — 15-down "(9,5,4)" over NEWCASTLE,
17-down "See 15" with no count of its own over UNDERLYME. tools/apply_solution.py,
tools/puzzle_integrity.py's check_length and the app all read a linked answer's
count off its leader, so a count sitting on a continuation is not a smaller
version of the same fact, it is a different one.

The solver scripts emit the other shape: a per-light count on each half, because
each light is what they measured. That shape is refused by
tools/file_penguin_puzzle.py — correctly, but once per puzzle, by hand, three
times for one mistake. This converts it instead, so the split shape is a thing
the route absorbs rather than a thing it stops for. file_penguin_puzzle.py calls
normalise_record() itself before building, which is what makes the wrong shape
unfilable rather than merely refused; run this CLI when you want to see or
record the rewrite.

THE ENUMERATION IS DERIVED FROM THE ANSWER wherever there is one, never from
the printed per-light counts. "(5,3,6)" is a statement about UNTER DEN LINDEN's words, and the words
are in the answer; the per-light counts are a statement about the grid, which
already knows its own light lengths. Splitting "5" and "9" back into "5,3,6" out
of the printed numbers is impossible — the 9 says nothing about where DEN ends.
So the fill's spaces and hyphens supply the word structure, the grid supplies
the totals, and a printed per-light count is used for one thing only: as a
cross-check that refuses when it disagrees with the answer (the fill lost a
space, or the answer is not the one the book counted).

A record with no answers is the one case that has nothing else to go on, and it
is a real one: a puzzle filed unsolved for the nightly backfill to finish. There
the printed per-light counts ARE the word structure the book gave for each
light, and only the join between two lights is supplied — as a comma, the way
this corpus reads a linked answer's split. See group_enumeration_from_counts.

A light boundary inside a linked answer is a word break, so the join between two
lights is written as a comma unless the earlier light's fill ends in a hyphen.
That is the whole corpus's reading: an answer is split across lights AT its
words.

It refuses rather than guesses. "See 19" in book 45 names both 19-across and
19-down; what settles it is that 19-across is itself a pointer ("See 17") and a
pointer cannot lead a group, with direction as the tiebreak below that — the
redirect names the light in the direction the continuation was printed against.
An ambiguity that survives both is an error, because picking wrong staples one
answer's count onto another answer's grid.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# "See 15", "See 11 down", "See 23 13 across, or 11" — a light whose clue lives
# on another light. The corpus spells continuations this way in every series;
# fetch_puzzle.is_continuation reads the same shape, and this keeps the number.
CONTINUATION = re.compile(r"^\s*See\s+(\d+)\b", re.IGNORECASE)

# "7,6" / "4-5" / "9,5,4": each count and the punctuation that follows it. The
# separator after the last count is the end of the answer and is never written.
ENUM_PART = re.compile(r"(\d+)\s*([,\-–/ ]?)")

HYPHENS = "-–—"


def continuation_target(clue):
    """The number a "See N" clue points at, or None if this clue is a real one."""
    m = CONTINUATION.match(clue or "")
    return int(m.group(1)) if m else None


def enumeration_parts(enumeration):
    """"9,5,4" -> [(9, ","), (5, ","), (4, "")]."""
    parts = []
    for count, sep in ENUM_PART.findall(enumeration or ""):
        parts.append((int(count), "-" if sep in HYPHENS else ("," if sep else "")))
    if not parts:
        raise SystemExit(f"enumeration {enumeration!r} holds no counts")
    parts[-1] = (parts[-1][0], "")
    return parts


def format_parts(parts):
    """[(5, ","), (3, ","), (6, "")] -> "5,3,6"."""
    return "".join(f"{count}{sep}" for count, sep in parts)


def answer_parts(answer):
    """The word structure of one light's answer: "ONE'S VOICE" -> [(4, ","), (5, "")].

    Letters only, so an apostrophe or a full stop counts for nothing; a space is
    a comma and a hyphen is a hyphen, which is exactly what an enumeration is.
    The last part's separator is the end of this light and is filled in by the
    caller, who is the only one that knows whether another light follows.
    """
    parts = []
    count = 0
    for ch in str(answer):
        if ch.isalpha():
            count += 1
        elif ch.isspace() or ch in HYPHENS:
            if count:
                parts.append((count, "-" if ch in HYPHENS else ","))
            count = 0
    if count:
        parts.append((count, ""))
    if not parts:
        raise SystemExit(f"answer {answer!r} holds no letters")
    return parts


def resolve_groups(entries):
    """Link each "See N" continuation to the light that carries its clue.

    Returns {entry id: [ids in reading order]} for the linked entries only, the
    leader first, every member mapped to the same list.

    The reference is by NUMBER — the book prints "See 15", not "See 15 down" —
    so a number naming two lights is resolved in this order:

      1. a pointer cannot lead a group, so a candidate whose own clue is "See M"
         is not a leader (book 45: "See 19" from 20-down, where 19-across is
         itself "See 17", leaves 19-down TURNED leading TURNED TO STONE);
      2. failing that, the redirect names the light in the direction the
         continuation was printed against;
      3. failing that, it is an error and not a guess.

    A group whose every candidate is a pointer is a chain — leg 3 pointing at
    leg 2 pointing at the leader — and is followed to its leader.
    """
    by_number = {}
    for e in entries:
        by_number.setdefault(e["number"], []).append(e)

    def leader_for(entry, seen):
        target = continuation_target(entry.get("clue"))
        candidates = [c for c in by_number.get(target, []) if c["id"] != entry["id"]]
        if not candidates:
            raise SystemExit(
                f"{entry['id']}: clue {entry['clue']!r} points at No {target}, "
                f"which names no other light")
        clued = [c for c in candidates if continuation_target(c.get("clue")) is None]
        pool = clued or candidates
        if len(pool) > 1:
            same = [c for c in pool if c["direction"] == entry["direction"]]
            pool = same or pool
        if len(pool) != 1:
            named = ", ".join(sorted(c["id"] for c in pool))
            raise SystemExit(
                f"{entry['id']}: clue {entry['clue']!r} points at No {target}, which "
                f"names {len(pool)} candidate lights ({named}) — cannot link it")
        found = pool[0]
        if continuation_target(found.get("clue")) is None:
            return found
        if found["id"] in seen:
            raise SystemExit(
                f"{entry['id']}: clue {entry['clue']!r} leads back to itself through "
                f"{found['id']} — a loop of pointers has no leader")
        return leader_for(found, seen | {entry["id"]})

    groups = {}
    for e in entries:
        if continuation_target(e.get("clue")) is None:
            continue
        leader = leader_for(e, {e["id"]})
        groups.setdefault(leader["id"], [leader["id"]])
        groups[leader["id"]].append(e["id"])
        groups[e["id"]] = groups[leader["id"]]
    return groups


def group_enumeration(group_ids, by_id, fill):
    """The whole linked answer's enumeration, read off the answer and the grid.

    Cross-checked against every printed per-light count the record still has:
    the counts must agree part for part, and where they do, the light's own
    punctuation is taken from the book rather than from the fill's spelling —
    the book is what printed the hyphen. A disagreement is refused, because it
    means the fill and the count are describing different answers.
    """
    parts = []
    for position, gid in enumerate(group_ids):
        entry = by_id[gid]
        answer = fill.get(gid)
        if not answer:
            raise SystemExit(f"{group_ids}: no answer for {gid}")
        mine = answer_parts(answer)
        held = sum(n for n, _ in mine)
        if held != entry["length"]:
            raise SystemExit(
                f"{gid}: answer {answer!r} holds {held} letters, the light is "
                f"{entry['length']} cells")
        printed = entry.get("enumeration")
        if printed:
            want = [n for n, _ in enumeration_parts(printed)]
            if want != [n for n, _ in mine]:
                raise SystemExit(
                    f"{gid}: the book counts ({printed}) but the answer {answer!r} "
                    f"reads ({format_parts(mine)}) — the fill and the count are not "
                    f"the same answer")
            mine = [(n, s) for (n, _), (_, s) in zip(mine, enumeration_parts(printed))]
        if position < len(group_ids) - 1:
            # The join between two lights. A linked answer is split AT a word,
            # so a comma, unless this light's fill ends the word on a hyphen.
            tail = "-" if str(answer).rstrip()[-1:] in HYPHENS else ","
            mine[-1] = (mine[-1][0], tail)
        else:
            mine[-1] = (mine[-1][0], "")
        parts.extend(mine)
    return parts


def group_enumeration_from_counts(group_ids, by_id):
    """The whole answer's enumeration when there is no answer to read it off.

    A puzzle can be filed before it is solved — the nightly cold solve in
    tools/daily_update.sh finishes it later — and such a record has the book's
    printed per-light counts and nothing else. Those counts are still the book's
    own statement of the words inside each light, so the only thing derived here
    is the JOIN between two lights, which the corpus already reads as a word
    break: a linked answer is split AT its words. Whether that break is a hyphen
    rather than a comma cannot be known without the answer, and a comma is what
    the corpus spells, so a comma is what is written; the solve that fills the
    grid does not rewrite it, because by then the count is on the leader and
    normalise_record leaves a leader-form record alone.

    A light that prints no count at all — book 27's 17-down, nine cells under
    "See 7" and nothing else — counts as one word of its own length. That is the
    weakest true statement available: its cells are in the answer, and where its
    words fall is not knowable until somebody solves it. It is not the same as
    dropping the group's internal breaks and printing one total. "(14)" over
    UNTER DEN LINDEN would say the answer is a single fourteen-letter word and
    would contradict the rule above, which the whole corpus reads: a linked
    answer is split AT its words, so the join between two lights is a break.
    "(5,9)" keeps the break the grid proves and guesses only inside the light
    nobody counted.

    It still refuses a printed count that does not add up to its own light,
    because that is a disagreement rather than a gap.
    """
    parts = []
    for position, gid in enumerate(group_ids):
        entry = by_id[gid]
        printed = entry.get("enumeration")
        if not printed:
            parts.append((entry["length"], "," if position < len(group_ids) - 1 else ""))
            continue
        mine = enumeration_parts(printed)
        held = sum(n for n, _ in mine)
        if held != entry["length"]:
            raise SystemExit(
                f"{gid}: the book counts ({printed}) = {held} letters, the light is "
                f"{entry['length']} cells")
        mine[-1] = (mine[-1][0], "," if position < len(group_ids) - 1 else "")
        parts.extend(mine)
    return parts


def normalise_record(record):
    """Rewrite every linked group in a solve record into leader form.

    Returns a list of human-readable changes, empty when the record was already
    in leader form — it is a no-op on a record that is already right, so it is
    safe to run on anything and safe to run twice.
    """
    entries = record["puzzle"]["entries"]
    by_id = {e["id"]: e for e in entries}
    fill = record.get("fill") or {}
    groups = resolve_groups(entries)

    changes = []
    for leader_id, group_ids in sorted(groups.items()):
        if group_ids[0] != leader_id:
            continue
        lights = [by_id[gid] for gid in group_ids]
        cells = sum(e["length"] for e in lights)
        was = by_id[leader_id].get("enumeration")
        strays = [e["id"] for e in lights[1:] if e.get("enumeration")]
        if not strays and was and sum(n for n, _ in enumeration_parts(was)) == cells:
            continue  # already leader form; the answer gets no vote over it

        # Off the answers where there are answers, off the book's printed
        # counts where there are not. An unsolved record is the second case for
        # every one of its groups; a partially-solved one can be both.
        if all(fill.get(gid) for gid in group_ids):
            parts = group_enumeration(group_ids, by_id, fill)
        else:
            parts = group_enumeration_from_counts(group_ids, by_id)
        counted = sum(n for n, _ in parts)
        if counted != cells:
            raise SystemExit(
                f"{group_ids}: the answers read ({format_parts(parts)}) = {counted} "
                f"letters, the grid holds {cells}")
        enumeration = format_parts(parts)
        by_id[leader_id]["enumeration"] = enumeration
        for e in lights[1:]:
            e["enumeration"] = None
        changes.append(
            f"{' + '.join(group_ids)}: leader was ({was or 'none'}), now ({enumeration}); "
            + (f"cleared the count on {', '.join(strays)}" if strays
               else "no stray counts to clear"))
    return changes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("records", nargs="+", help="solve records, e.g. /tmp/penguin_solve_book18.json")
    ap.add_argument("--check", action="store_true",
                    help="report what would change and exit 1 if anything would, writing nothing")
    args = ap.parse_args(argv)

    pending = 0
    for name in args.records:
        path = Path(name)
        record = json.loads(path.read_text(encoding="utf-8"))
        changes = normalise_record(record)
        if not changes:
            print(f"{path}: already leader form, nothing to do")
            continue
        pending += len(changes)
        verb = "would rewrite" if args.check else "rewrote"
        print(f"{path}: {verb} {len(changes)} linked group(s)")
        for line in changes:
            print(f"  {line}")
        if not args.check:
            path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    return 1 if (args.check and pending) else 0


if __name__ == "__main__":
    sys.exit(main())
