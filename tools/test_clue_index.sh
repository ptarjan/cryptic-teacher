#!/bin/bash
# Does StoredClueIndex answer exactly what ClueIndex.build() answers, as files
# are added, edited and deleted, and when its store is corrupt?
#
#     bash tools/test_clue_index.sh
#
# A scratch git checkout holds a few real puzzles plus a copy of one filed
# under another id. After each change to the tree (an untracked copy, an
# edited file, a deleted file) a fresh StoredClueIndex.open() on a scratch
# store must give build()'s ids, sizes, matches() for every puzzle and pairs(),
# and only the changed files may be parsed again. A store overwritten with
# garbage is rebuilt, and add()/discard() change one process's view as they
# do on a ClueIndex. Never reads ~/.cache: the store is in the scratch dir.
set -u
cd "$(dirname "$0")/.." || exit 1

python3 - <<'EOF'
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import clue_index
import puzzle_paths
from clue_index import ClueIndex, StoredClueIndex

fails = []
real = [puzzle_paths.find(p) for p in ("times-27331", "times-29539", "cryptic-25328",
                                       "everyman-4165", "book-8001")]
scratch = Path(tempfile.mkdtemp())
store = scratch / "store"
root = scratch / "repo"
puzzle_paths.PUZZLE_DIR = root / "puzzles"
for path in real:
    dest = puzzle_paths.PUZZLE_DIR / path.relative_to(path.parents[2])
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, dest)


def git(*args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


git("init", "-q")
git("add", "puzzles")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fixture")

parsed = []
real_parse = clue_index._parse
clue_index._parse = lambda data: parsed.append(json.loads(data).get("id")) or real_parse(data)


def same(tag, reparsed):
    parsed.clear()
    old, new = ClueIndex.build(), StoredClueIndex.open(store)
    sizes = {pid: n for pid, (_, n) in new.by_pid.items()}
    if sizes != old.size:
        fails.append(f"{tag}: ids/sizes {sizes} != {old.size}")
    for pid, keys in old.keys.items():
        if sorted(old.matches(pid, keys)) != sorted(new.matches(pid, keys)):
            fails.append(f"{tag}: matches({pid}) {new.matches(pid, keys)} != {old.matches(pid, keys)}")
    if old.pairs() != new.pairs():
        fails.append(f"{tag}: pairs {new.pairs()} != {old.pairs()}")
    if sorted(parsed) != sorted(reparsed):
        fails.append(f"{tag}: parsed {sorted(parsed)}, wanted only {sorted(reparsed)}")
    print(f"  {tag}: {len(old.size)} ids, {len(old.pairs())} pair(s), parsed {len(parsed)}")
    return old, new


ids = [p.stem for p in real]
same("fresh store", ids)
same("unchanged tree", [])

copy = json.loads(real[0].read_text())
copy["id"] = "times-1"
copy_path = puzzle_paths.find("times-27331").with_name("times-1.json")
copy_path.write_text(json.dumps(copy))
old, _ = same("untracked copy", ["times-1"])
if not any("times-1" in pair for pair in old.pairs()):
    fails.append("the fixture copy is no near-duplicate: the test proves nothing")

edited = json.loads(real[0].read_text())
for e in edited["entries"][:12]:
    e["clue"]["text"] += " reworded"
real_path = puzzle_paths.find("times-27331")
real_path.write_text(json.dumps(edited))
same("edited tracked file", ["times-27331"])

copy_path.unlink()
same("deleted copy", [])

(store / next(p.name for p in store.glob("clue-keys-*.sqlite"))).write_bytes(b"not a database" * 100)
for f in store.glob("clue-keys-*.sqlite-*"):
    f.unlink()
same("corrupt store", ids)

old, new = same("again", [])
a = "cryptic-25328"
for idx in (old, new):
    idx.discard(a)
    idx.add("times-2", json.loads((puzzle_paths.find("everyman-4165")).read_text()))
for pid, keys in old.keys.items():
    if sorted(old.matches(pid, keys)) != sorted(new.matches(pid, keys)):
        fails.append(f"after add/discard: matches({pid}) {new.matches(pid, keys)} != {old.matches(pid, keys)}")
if old.pairs() != new.pairs():
    fails.append(f"after add/discard: pairs {new.pairs()} != {old.pairs()}")

shutil.rmtree(scratch)
for f in fails:
    print("  FAIL:", f)
print("ok" if not fails else f"{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
EOF
