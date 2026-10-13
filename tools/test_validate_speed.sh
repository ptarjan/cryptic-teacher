#!/usr/bin/env bash
# The deploy's "Check every annotation" step runs validate_annotations over the
# whole corpus (~51,000 files), so a per-file cost that creeps up becomes
# minutes (124s -> 247s in a day, 2026-10-13, budget 200s). The guard is the cost
# of 40 annotated puzzles in CPU seconds on one core, with 4x headroom over
# today's ~45ms a puzzle; a regression of that size fails here, long before the
# deploy. And the two caches the speed rests on are in place.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -I - <<'PY'
import resource, sys
sys.path[:0] = ["tools"]
import find_answer_leaks, puzzle_paths, puzzle_schema, validate_annotations as va

files = []
for path in puzzle_paths.puzzle_files()[::97]:
    if '"annotation"' in path.read_text(encoding="utf-8"):
        files.append(path)
    if len(files) == 40:
        break
assert len(files) == 40, f"test_validate_speed: only {len(files)} annotated puzzles sampled"
allowed = va.load_backlog()
t0 = resource.getrusage(resource.RUSAGE_SELF)
for f in files:
    va.check_one(f, True, allowed)
t1 = resource.getrusage(resource.RUSAGE_SELF)
cpu = t1.ru_utime + t1.ru_stime - t0.ru_utime - t0.ru_stime
per = cpu / len(files)
LIMIT = 0.2
assert per < LIMIT, (f"test_validate_speed: {per * 1000:.0f}ms CPU a puzzle (limit {LIMIT * 1000:.0f}ms): "
                     f"the full check's per-file cost grew; profile it with cProfile on a sample")
assert find_answer_leaks._spans_list.cache_info().hits, "find_answer_leaks._spans is not cached"
assert puzzle_schema._PLANS, "puzzle_schema._check is not planning each schema node once"
print(f"test_validate_speed: ok ({per * 1000:.0f}ms CPU a puzzle over {len(files)})")
PY
