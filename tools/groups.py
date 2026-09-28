"""Linked answers: one answer spread over several lights ("See 21").

The leader, the light the answer starts on, carries `group`: the answer's
lights in order, itself first, naming again any light the answer repeats.
Every other light of the answer carries
nothing, neither a group nor an annotation. A light may continue more than
one answer: cryptic-27188's 12-across AND ONE ends both 1-across's HUNDRED AND
ONE and 13-across's THOUSAND AND ONE, so it is in both leaders' groups.
"""


def leaders(entries):
    """{leader id: its group} for every group in the puzzle."""
    return {e["id"]: e["group"] for e in entries if e.get("group")}


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
        if e["id"] in claims:
            e["group"] = list(claims[e["id"]])
    return entries


def collapse(entries):
    """Drop `group` from every light that does not lead it, in place."""
    for e in entries:
        if e.get("group") and e["group"][0] != e["id"]:
            del e["group"]
    return entries
