"""Linked answers: one answer spread over several lights ("See 21").

The leader, the light the answer starts on, carries `group`: the answer's
lights in order, itself first, naming again any light the answer repeats.
Every other light of the answer carries
nothing, neither a group nor an annotation. A light may continue more than
one answer: cryptic-27188's 12-across AND ONE ends both 1-across's HUNDRED AND
ONE and 13-across's THOUSAND AND ONE, so it is in both leaders' groups.
"""


def entry_id(e):
    """An entry's id, "<number>-<direction>" ("21-across"): what `group` lists
    and annotations are keyed by. Derived, never stored."""
    return f"{e['number']}-{e['direction']}"


def leaders(entries):
    """{leader id: its group} for every group in the puzzle."""
    return {entry_id(e): e["group"] for e in entries if e.get("group")}


def group_of(entries):
    """{light id: the group it is in} for every linked light. A light in more
    than one group maps to the one it leads, else the first leader's in entry
    order."""
    out = dict(leaders(entries))
    for group in list(out.values()):
        for eid in group:
            out.setdefault(eid, group)
    return out


def leader_of(entries):
    """{continuation id: its leader's id}, first leader in entry order."""
    out = {}
    for lead, group in leaders(entries).items():
        for eid in group[1:]:
            if eid != lead:
                out.setdefault(eid, lead)
    return out


def spread(entries):
    """Give every light of a group that group, in place: the per-light claims
    the Guardian ships and fetch_puzzle's reconciliation reasons over. Undone
    by collapse() before the puzzle is written."""
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
