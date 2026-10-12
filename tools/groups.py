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
"""


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


def leaders(entries):
    """{leader id: its first group} for every leader in the puzzle; linked()
    gives a leader's alsoLeads groups too."""
    return {entry_id(e): e["group"] for e in entries if e.get("group")}


def group_of(entries):
    """{light id: the group it is in} for every linked light. A light in more
    than one group maps to the first it leads, else the first leader's in
    entry order."""
    out = dict(leaders(entries))
    for _, h in linked(entries):
        for eid in h["group"]:
            out.setdefault(eid, h["group"])
    return out


def holder_of(entries):
    """{continuation id: the holder of its answer}, the first in entry order:
    where its clue, group and annotation live."""
    out = {}
    for lead, h in linked(entries):
        for eid in h["group"][1:]:
            if eid != entry_id(lead):
                out.setdefault(eid, h)
    return out


def leader_of(entries):
    """{continuation id: its leader's id}, first leader in entry order."""
    out = {}
    for lead, h in linked(entries):
        for eid in h["group"][1:]:
            if eid != entry_id(lead):
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
