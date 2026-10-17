#!/usr/bin/env python3
# The deploy's full annotation check runs as 4 shards (`--shard i/n`), one step
# each. Every puzzle must be checked by exactly one: the shards are disjoint,
# their union is the whole corpus, the split does not move between runs, and
# a malformed or mixed-up --shard is refused rather than checking nothing.
#
#     python3 tools/test_validate_shard.py
import os
import sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
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
print(f"test_validate_shard: ok ({len(paths)} puzzles)")
