"""Linked answers: one answer spread over several lights ("See 21").

The leader, the light the answer starts on, carries `group`: the answer's
lights in order, itself first, naming again any light the answer repeats.
Every other light of the answer carries
nothing, neither a group nor an annotation. A light may continue more than
one answer: cryptic-27188's 12-across AND ONE ends both 1-across's HUNDRED AND
ONE and 13-across's THOUSAND AND ONE, so it is in both leaders' groups.

A light may also start more than one answer: Genius 209's 22-across IVOR
starts both IVOR HUGH JEGO and IVOR SORE BEACH BUM, two printed clues. The
first is the entry's own clue, group and annotation; each further one is an
item of the entry's `alsoLeads`, {clue, group, annotation}. The holder of a
linked answer is the dict carrying its clue, group and annotation: the leader
entry itself, or one of those items.

A light of a group may also be an answer of its own: cryptic-21893's 21-down
THERE and 1-across PUBLIC each carry a clue, and also finish 11-across's
BATTLE HYMN OF THE REPUBLIC. The holder names such lights in `selfClued`;
they keep their own clue, annotation and group, and are not that answer's
continuations (holder_of, leader_of and group_of pass them by).
"""

import re

# What a continuation leg's clue is made of once its enumeration is off: the
# word "see", the numbers it points at, the directions they name ("across",
# "dn", or glued on: "See 12a") and the words that join them. Nothing else.
# A clue that OPENS "See N" and goes on is wordplay referring to N, not a
# pointer: The Nation's 3257 printed 1-across "See 2 if confused about final two
# parts of clues (7)" (WITNESS, TWINS+ES), and cryptic 27,884 "See 5 across out
# to find another date". The space after "see" is optional because the paper's
# markup does not always print one: cryptic-23101's 9-across reads "See10".
# This is the one statement of the shape: fetch_puzzle.is_continuation, the
# linked-enumeration normaliser, every parser and cross_validate read it here.
POINTER = re.compile(
    r"(?i)^see(?![a-z])[\s\d,&.]*"
    r"(?:(?:across|down|and|or|above|dn|ac|a|d)\b[\s\d,&.]*)*$")
# The leg's own cell count some papers print beside a pointer ("See 2 (6)").
_POINTER_COUNT = re.compile(r"\s*\(\s*\d[\d\s,.;'’\-–]*\)\s*$")
_WRAPPED = re.compile(r"(?i)^\(\s*(see\b[^()]*)\)")
_NUMBER = re.compile(r"\d+")


def is_pointer(text, counted=False):
    """Is this clue text nothing but "See N" (a pointer at another light)?

    `counted` also accepts the leg's own count after it ("See 2 (6)",
    "(See 16 Across) (3)") for readers that see the raw printed line."""
    text = (text or "").strip(" .…\t\n")
    if counted:
        text = _POINTER_COUNT.sub("", _WRAPPED.sub(r"\1", text)).strip(" .…\t\n")
    return bool(POINTER.match(text)) and bool(_NUMBER.search(text))


def pointer_target(text, counted=False):
    """The first number a pointer names, or None for a real clue (is_pointer)."""
    if not is_pointer(text, counted):
        return None
    return int(_NUMBER.search(text).group())


def entry_id(e):
    """An entry's id, "<number>-<direction>" ("21-across"): what `group` lists
    and annotations are keyed by. Derived, never stored."""
    return f"{e['number']}-{e['direction']}"


def holders(e):
    """The linked answers entry e starts, as holders: e itself when it has a
    group, then each of its alsoLeads; [] when it leads none."""
    if not e.get("group"):
        return []
    return [e] + list(e.get("alsoLeads") or [])


def linked(entries):
    """[(leader entry, holder)] for every linked answer in the puzzle, in
    entry order, a leader's own answer before its alsoLeads."""
    return [(e, h) for e in entries for h in holders(e)]


def clue_id(e, k):
    """The id the annotate run gives entry e's alsoLeads[k]: "22-across/2",
    the second linked answer 22-across starts (its own clue is the first)."""
    return f"{entry_id(e)}/{k + 2}"


def also_clues(entries):
    """[(clue id, entry index, k, item)] for every alsoLeads item."""
    return [(clue_id(e, k), i, k, item) for i, e in enumerate(entries)
            for k, item in enumerate(e.get("alsoLeads") or [])]


def as_leader(puzzle, i, k):
    """A copy of puzzle in which entries[i]'s alsoLeads[k] is that light's
    own clue, group and annotation, and it leads nothing else: what a check
    written for one answer per light reads to check that answer."""
    entries = list(puzzle["entries"])
    e = {key: v for key, v in entries[i].items() if key not in ("alsoLeads", "annotation")}
    e.update(entries[i]["alsoLeads"][k])
    entries[i] = e
    return {**puzzle, "entries": entries}


OFF_GRID = "offgrid"


def off_grid(puzzle):
    """[(id, item)] for each clue whose answer takes no light (`offGrid`):
    item k (1-based) is "<k>-offgrid", what entry_id gives its as_entry."""
    return [(f"{k}-{OFF_GRID}", item) for k, item in enumerate(puzzle.get("offGrid") or [], 1)]


def as_entry(puzzle, cid):
    """The `offGrid` clue `cid` seen as an entry ({number: k, direction:
    "offgrid", length: its enumeration's}), its clue, solution and annotation
    the item's own objects: what a reader of entries reads to treat it as a clue."""
    import enumeration
    k = int(cid.split("-")[0])
    item = puzzle["offGrid"][k - 1]
    length = sum(enumeration.counts(item["clue"].get("enumeration"))) or len(item.get("solution") or "")
    return {"number": k, "direction": OFF_GRID, "length": length, **item}


def alone(puzzle, cid):
    """A copy of puzzle whose one entry is the `offGrid` clue `cid` on a
    light of its own (position 0,0 of a grid just its size): what a check
    written for entries reads to check that clue, with no crossings."""
    e = {**as_entry(puzzle, cid), "direction": "across", "position": {"x": 0, "y": 0}}
    return {**{k: v for k, v in puzzle.items() if k != "offGrid"},
            "dimensions": {"cols": max(e["length"], 1), "rows": 1}, "entries": [e]}


def leaders(entries):
    """{leader id: its first group} for every leader in the puzzle; linked()
    gives a leader's alsoLeads groups too."""
    return {entry_id(e): e["group"] for e in entries if e.get("group")}


def self_clued(holder):
    """The lights of holder's group that are answers of their own too
    (`selfClued`): not its continuations."""
    return set(holder.get("selfClued") or ())


def group_of(entries):
    """{light id: the group it is in} for every linked light. A light in more
    than one group maps to the first it leads, else the first leader's in
    entry order. A self-clued light is in no group but its own."""
    out = dict(leaders(entries))
    for _, h in linked(entries):
        for eid in h["group"]:
            if eid not in self_clued(h):
                out.setdefault(eid, h["group"])
    return out


def holder_of(entries):
    """{continuation id: the holder of its answer}, the first in entry order:
    where its clue, group and annotation live."""
    out = {}
    for lead, h in linked(entries):
        for eid in h["group"][1:]:
            if eid != entry_id(lead) and eid not in self_clued(h):
                out.setdefault(eid, h)
    return out


def leader_of(entries):
    """{continuation id: its leader's id}, first leader in entry order."""
    out = {}
    for lead, h in linked(entries):
        for eid in h["group"][1:]:
            if eid != entry_id(lead) and eid not in self_clued(h):
                out.setdefault(eid, entry_id(lead))
    return out


def spread(entries):
    """Give every light of a group that group, in place: the per-light claims
    the Guardian ships and fetch_puzzle's reconciliation reasons over. Undone
    by collapse() before the puzzle is written. alsoLeads stay where they are."""
    claims = group_of(entries)
    for e in entries:
        if entry_id(e) in claims:
            e["group"] = list(claims[entry_id(e)])
    return entries


def collapse(entries):
    """Drop `group` from every light that does not lead it, in place."""
    for e in entries:
        if e.get("group") and e["group"][0] != entry_id(e):
            del e["group"]
    return entries
