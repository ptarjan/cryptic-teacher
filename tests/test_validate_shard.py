#!/usr/bin/env python3
# The deploy's full annotation check runs as 6 shards (`--shard i/n`), one step
# each. Every puzzle must be checked by exactly one: the shards are disjoint,
# their union is the whole corpus, the split does not move between runs, and
# a malformed or mixed-up --shard is refused rather than checking nothing.
#
#     python3 tests/test_validate_shard.py
import os
import sys

os.chdir(os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"), ".."))
sys.path[:0] = ["tools"]
import puzzle_paths, validate_annotations as va

paths = puzzle_paths.puzzle_files()
assert len(paths) > 1000, f"test_validate_shard: only {len(paths)} puzzles"
for n in (1, 4, 7):
    parts = [va.shard_slice(paths, (i, n)) for i in range(n)]
    seen = [p for part in parts for p in part]
    assert len(seen) == len(set(seen)), f"shards of {n} overlap"
    assert set(seen) == set(paths), f"shards of {n} do not cover every puzzle"
    if n > 1:
        assert all(len(part) > len(paths) // n // 2 for part in parts), f"shards of {n} are lopsided"
assert va.shard_slice(paths, (1, 4)) == va.shard_slice(list(paths), (1, 4)), "split is not stable"
assert va.shard_of("x", 4) == va.shard_of("x", 4)

assert va.take_shard_arg(["--shard", "2/4"]) == ([], (2, 4))
assert va.take_shard_arg(["--unscoped"]) == (["--unscoped"], None)
for bad in (["--shard"], ["--shard", "4/4"], ["--shard", "a/b"]):
    try:
        va.take_shard_arg(bad)
    except SystemExit:
        continue
    raise AssertionError(f"{bad} was accepted")
for argv in (["--shard", "0/4", "--tighten"], ["--shard", "0/4", "123"]):
    try:
        va.main(argv)
    except SystemExit:
        continue
    raise AssertionError(f"{argv} was accepted")
# The ratchet --tighten writes. A full run saw every puzzle; a run given ids saw
# only those, so it may only LOWER their allowances and leaves the rest alone.
fields = list(va.BACKLOG_MARKERS)
f0, f1 = fields[0], fields[1]
zero = {f: 0 for f in fields}
allowed = {f0: {"a-1": 5, "a-2": 3, "a-3": 2}, f1: {"a-1": 1}}   # the other fields have no list yet
seen = {"a-1": {**zero, f0: 2, f1: 4}, "a-2": {**zero, f0: 9}, "a-4": {**zero, f0: 7}}

full = va.ratchet_backlog(seen, allowed, True)
assert full[f0] == {"a-1": 2, "a-2": 3, "a-4": 7}, full[f0]   # min(); new puzzle recorded; unseen a-3 dropped
assert full[f1] == {"a-1": 1}
assert set(full) == set(fields), "a full run records every field"

part = va.ratchet_backlog(seen, allowed, False)
assert part[f0] == {"a-1": 2, "a-2": 3, "a-3": 2}, part[f0]   # lowered, never raised; a-3 kept verbatim; a-4 not added
assert part[f1] == {"a-1": 1}, part[f1]                       # observed 4 > allowed 1: the tighter cap stays
assert set(part) == {f0, f1}, "a scoped run adds no field the file lacks"
assert va.ratchet_backlog({"a-2": dict(zero)}, allowed, False)[f0] == {"a-1": 5, "a-3": 2}   # drained to 0: entry leaves

print(f"test_validate_shard: ok ({len(paths)} puzzles)")
