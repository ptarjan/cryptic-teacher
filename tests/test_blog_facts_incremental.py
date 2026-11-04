#!/usr/bin/env python3
# Is what blog_facts.py does over the changed slice alone what a full build makes?
#
#     python3 tests/test_blog_facts_incremental.py
#
# Paul, 2026-11-03: "Don't do full corpus things when only a bit changes." Three
# steps of the nightly reuse what an earlier run made, and each must give the
# bytes a run from nothing gives:
#   - the lexicon merge reads the chunks' counts summed in groups (letter_facts
#     _stored_groups), and a moved chunk sums only its group again;
#   - the letter pass lays the clue results into the sidecars (_lay_out), reading
#     only those whose result or sidecar moved since a run laid them out;
#   - the blogs-only write regrafts (blog_facts._Regrafts) only the sidecars
#     whose line or bytes moved.
#   - the corpus pack (letter_facts.packed_rows) re-encodes only the puzzles whose
#     sidecar or clues moved, and none when nothing did.
# All on fixtures in a temp dir: no corpus, no network.
import collections
import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
sys.path.insert(0, "tests")

import blog_facts
import blog_store
import letter_facts as l
from test_blog_facts_skip import OLD, REC


def deep(x):
    """`x` with every dict as its list of items, so == compares order too."""
    if isinstance(x, dict):
        return [(k, deep(v)) for k, v in x.items()]
    if isinstance(x, (list, tuple)):
        return [deep(v) for v in x]
    if isinstance(x, (bytearray, l.array.array)):
        return bytes(x)
    if isinstance(x, l._Keys):
        return list(x)
    return x


def shape(lexicons):
    return [deep({k: v for k, v in vars(x).items() if isinstance(v, dict)}) for x in lexicons]


def corpus_rows(n=300, moved=None):
    rows = []
    for i in range(n):
        rows.append((f"p{i:03}", "1a", f"Ape in rage heading west no {i} (4)", "LEMUR",
                     {"blocks": [["LE", "rage"], ["MUR", "in"]], "definition": ["Ape"],
                      "indicators": [{"text": "heading west", "for": "reversal"}]}))
        rows.append((f"p{i:03}", "2d", f"Bird {i % 7} on wire to the left (4)", "ERIW",
                     {"blocks": [["ERI", "wire"], ["W", "to the left"]], "definition": ["Bird"]}))
    if moved is not None:
        rows[moved] = (*rows[moved][:4], {"blocks": [["LE", "rage"]], "definition": ["Ape in"]})
    return rows


def lexicons(tmp):
    ours = [("q1", "3a", "Wire bird in rage (5)", "LEMUR", {"blocks": [["LEM", "Wire bird"], ["UR", "in rage"]]})]
    l.CHUNK, l.GROUP = 8, 3  # ~40 chunks in ~13 groups, so grouping is exercised
    corpus = l.Packed(corpus_rows())
    assert sum(1 for _ in l._chunked(corpus.with_pickled())) > 20

    # The order-sensitive merge: a sum of groups in order is the sum of the chunks.
    parts = [l._chunk_counts(([raw for _, raw in ch], True)) for ch in l._chunked(corpus.with_pickled())]
    flat_both, flat_reach = l._reach(parts)
    for cuts in ([5], [1, 2, 17], list(range(1, len(parts)))):
        groups = [l._summed(parts[a:b]) for a, b in zip([0, *cuts], [*cuts, len(parts)])]
        both, reach = l._reach(groups)
        assert deep(both) == deep(flat_both) and deep(reach) == deep(flat_reach), cuts
        assert deep(l._merged(groups, reach)) == deep(l._merged(parts, flat_reach)), cuts

    # The groups a store lacks are summed in a forked child: the same lexicons.
    forked = l._open_store(str(tmp / "forked.sqlite"))
    assert shape(l._cached_lexicons(forked, corpus, ours, 1)[0]) == shape(l._lexicons(corpus, ours, 1)), \
        "groups summed in a child differ from a full build"
    forked.close()
    l.GROUPS_IN_CHILD = False  # counted in this process from here on

    conn = l._open_store(str(tmp / "s.sqlite"))
    summed = []
    real = l._summed
    l._summed = lambda parts: summed.append(1) or real(parts)
    full = l._lexicons(corpus, ours, 1)
    cold, gen = l._cached_lexicons(conn, corpus, ours, 1)
    n_groups = len(summed)
    assert n_groups > 2, n_groups
    assert shape(cold) == shape(full), "grouped merge, cold store, differs from a full build"
    summed.clear()
    warm, gen2 = l._cached_lexicons(conn, corpus, ours, 1)
    assert shape(warm) == shape(full) and not summed and gen2 == gen, "a warm store must sum no group again"

    moved = l.Packed(corpus_rows(moved=123))
    summed.clear()
    counted = []
    real_counts = l._chunk_counts
    l._chunk_counts = lambda t: counted.append(1) or real_counts(t)
    got, gen3 = l._cached_lexicons(conn, moved, ours, 1)
    assert shape(got) == shape(l._lexicons(moved, ours, 1)), "one moved puzzle: grouped merge differs from a full build"
    # Its chunk is counted again and its group (unless the chunk is a group alone) summed again: no other.
    assert len(counted) == 1 and len(summed) <= 1 and gen3 != gen, (len(counted), len(summed))
    l._summed, l._chunk_counts = real, real_counts
    conn.close()
    print("ok   the grouped lexicon merge is a full build's, dict order and all; one moved chunk sums one group")


def sidecars(tmp, n=6):
    """n sidecars in a temp dir, blog_store.files pointed at them."""
    sides = tmp / "sides"
    shutil.rmtree(sides, ignore_errors=True)
    sides.mkdir()
    for i in range(n):
        (sides / f"p{i:03}{blog_store.SUFFIX}").write_text(blog_store.encode(REC))
    blog_store.files = lambda series=None: {p.name[:-len(blog_store.SUFFIX)]: p for p in sorted(sides.iterdir())}
    return sides


def results(n=6, moved=None):
    """{pid: clue results} as the letter pass gives them; p001 has none."""
    out = {}
    for i in range(n):
        if i == 1:
            continue
        new = {eid: {**v, "inferred": ["type"]} if eid == "5-down" else dict(v) for eid, v in OLD["entries"].items()}
        if i == moved:
            new["6-down"] = {"type": ["charade"], "inferred": ["type"]}
        out[f"p{i:03}"] = new
    return out


def full_lay_out(n, res):
    """The loop letter_facts.write ran before it kept anything: every sidecar
    read, the results put in, encoded, written if its bytes moved."""
    tally = collections.Counter()
    for pid, f in blog_store.files().items():
        rec = blog_store.read(f)
        new = res.get(pid)
        if new:
            tally.update(k for v in new.values() for k in v.get("inferred", ()))
            rec["entries"] = new
        blog_store.put(f, blog_store.encode(rec))
    return tally


def snapshot(sides):
    return {p.name: p.read_bytes() for p in sorted(sides.iterdir())}


def lay_out(tmp):
    conn = l._open_store(str(tmp / "laid.sqlite"))
    stream = lambda res: ((pid, pickle.dumps(v, pickle.HIGHEST_PROTOCOL)) for pid, v in sorted(res.items()))
    calls = []
    real = l._laid
    l._laid = lambda data, new: calls.append(1) or real(data, new)

    sides = sidecars(tmp)
    want_tally = full_lay_out(6, results())
    want = snapshot(sides)
    sides = sidecars(tmp)  # the same sidecars afresh, laid out the incremental way
    tally = l._lay_out(conn, stream(results()))
    assert snapshot(sides) == want and tally == want_tally, "a cold lay-out differs from the full loop"
    calls.clear()
    # The five whose bytes moved last time are laid out once more (a write is never
    # kept, being made of bytes no longer there); p001, left as it was, is not.
    tally = l._lay_out(conn, stream(results()))
    assert snapshot(sides) == want and tally == want_tally and len(calls) == 5, len(calls)
    calls.clear()
    tally = l._lay_out(conn, stream(results()))
    assert snapshot(sides) == want and tally == want_tally and not calls, f"nothing moved, yet {len(calls)} laid out"

    # One result moves, one sidecar is edited by hand: those two alone are read, and
    # every file is what the full loop makes of the same inputs.
    (sides / f"p004{blog_store.SUFFIX}").write_text(blog_store.encode({**REC, "url": "https://example.com/x/"}))
    ref = tmp / "ref"
    shutil.rmtree(ref, ignore_errors=True)
    shutil.copytree(sides, ref)
    calls.clear()
    tally = l._lay_out(conn, stream(results(moved=2)))
    assert len(calls) == 2, f"one result and one sidecar moved, yet {len(calls)} laid out"
    got = snapshot(sides)
    files = blog_store.files
    blog_store.files = lambda series=None: {p.name[:-len(blog_store.SUFFIX)]: p for p in sorted(ref.iterdir())}
    want_tally = full_lay_out(6, results(moved=2))
    blog_store.files = files
    assert got == snapshot(ref) and tally == want_tally, "after a move the lay-out differs from the full loop"

    # A results stream out of step with the sidecars is still refused.
    try:
        l._lay_out(conn, (r for r in [("zzz", pickle.dumps({}))]))
        raise AssertionError("out of step, not refused")
    except SystemExit:
        pass
    l._laid = real
    conn.close()
    print("ok   the letter pass lays out only moved sidecars, byte for byte the full loop's")


def regrafts(tmp):
    blog_facts.INDEX = tmp / "index.sqlite"
    side = tmp / "r.blog"
    calls = []
    real = blog_facts._regraft
    blog_facts._regraft = lambda body, data: calls.append(1) or real(body, data)
    body = blog_store.encode(REC)
    cases = [("same", OLD, REC), ("added", OLD, {**REC, "entries": {**REC["entries"], "6-down": {"type": ["charade"]}}}),
             ("moved", OLD, {**REC, "url": "https://example.com/other/"})]
    for name, old, rec in cases:
        body = blog_store.encode(rec)
        side.write_text(blog_store.encode(old))
        want = real(body, side.read_bytes())
        for run in range(3):
            calls.clear()
            r = blog_facts._Regrafts()
            got = r("p001", body, side)
            r.close()
            assert got == want, (name, run)
            # An outcome that is one of its inputs is kept after the first run; any other is made each run.
            kept = want in (body, side.read_text())
            assert len(calls) == (1 if run == 0 or not kept else 0), (name, run, len(calls))
    side.write_text(blog_store.encode(OLD) + " ")  # the sidecar's bytes move: regrafted again
    calls.clear()
    r = blog_facts._Regrafts()
    assert r("p001", blog_store.encode(REC), side) == real(blog_store.encode(REC), side.read_bytes()) and len(calls) == 1
    r.close()
    blog_facts._regraft = real
    print("ok   the blogs-only write regrafts only moved sidecars, as the full write does")


def pack(tmp):
    conn = l._open_store(str(tmp / "pack.sqlite"))
    sides = sidecars(tmp, 8)
    clues = [("5-down", "Ape in rage (5)", "LEMUR"), ("6-down", "Bird on wire (4)", "ERIW"), ("7-down", "No sidecar entry (3)", "ABC")]
    real_held, real_rows = l._held_clues, l._puzzle_rows
    l._held_clues = lambda pids: {pid: clues for pid in pids}
    made = []
    l._puzzle_rows = lambda *a, **k: made.append(a[0]) or real_rows(*a, **k)

    def same(got, want, what):
        assert got._state() == want._state() and list(got.pickled()) == list(want.pickled()), what

    want = l.Packed(l.rows())
    assert len(want) == 8 * 3
    same(l.packed_rows(None), want, "no store")
    made.clear()  # the full rows and the no-store pack built every puzzle too; count the cold pack alone
    same(l.packed_rows(conn), want, "cold pack differs from a full one")
    assert len(made) == 8, made
    made.clear()
    same(l.packed_rows(conn), want, "warm pack differs from a full one")
    assert not made, f"nothing moved, yet {len(made)} puzzles packed"

    # One sidecar moves: that puzzle alone is packed again, and the pack is a full one's.
    (sides / f"p003{blog_store.SUFFIX}").write_text(blog_store.encode({**REC, "entries": {"5-down": {"type": ["anagram"]}}}))
    want = l.Packed(l.rows())
    made.clear()
    same(l.packed_rows(conn), want, "after a move the pack differs from a full one")
    assert made == ["p003"], made
    made.clear()
    same(l.packed_rows(conn), want, "warm again")
    assert not made

    # One puzzle's clues move.
    clues[:] = [("5-down", "Ape in rage (5)", "LEMUR")]
    want = l.Packed(l.rows())
    made.clear()
    same(l.packed_rows(conn), want, "all clues moved")
    assert len(made) == 8
    l._held_clues, l._puzzle_rows = real_held, real_rows
    conn.close()
    print("ok   the pack re-encodes only moved puzzles, skips when none moved, and is a full pack's bytes")


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ.pop("CT_DEADLINE", None)
    try:
        lexicons(tmp)
        lay_out(tmp)
        regrafts(tmp)
        pack(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("all incremental blog_facts checks passed")


if __name__ == "__main__":
    main()
