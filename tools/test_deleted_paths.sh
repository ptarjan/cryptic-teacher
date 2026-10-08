#!/bin/bash
# Does deleted_paths.last_deletion() give what `git log -1 --diff-filter=D --
# <path>` gives, as HEAD moves forward, back, sideways and is rewritten?
#
#     bash tools/test_deleted_paths.sh
set -uo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
export GIT_CONFIG_NOSYSTEM=1 HOME="$tmp/home" GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t \
  GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME"
TOOLS="$PWD/tools" python3 - "$tmp/repo" <<'PY'
import os, subprocess, sys
sys.path.insert(0, os.environ["TOOLS"])
import deleted_paths as d

repo = sys.argv[1]
os.makedirs(repo)
def git(*a):
    return subprocess.run(["git", "-C", repo, *a], check=True,
                          capture_output=True, text=True).stdout.strip()
def put(rel, text):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(text)
def commit(msg):
    git("add", "-A"); git("commit", "-qm", msg); return git("rev-parse", "HEAD")

fails = 0
PATHS = ["p/a.json", "p/b.json", "p/c.json", "p/2020/m.json", "p/2021/m.json",
         "p/never.json", "q/x.json"]
def agree(why):
    global fails
    d._memo.clear()
    before = fails
    for rel in PATHS:
        want = git("log", "-1", "--diff-filter=D", "--format=%H", "--", rel) or None
        got = d.last_deletion(repo, rel, "p")
        if got != want:
            print(f"  FAIL: {why}: {rel} gave {got}, git log gives {want}")
            fails += 1
    if fails == before:
        print(f"  ok: {why}")

git("init", "-q", "-b", "master")
put("p/a.json", "1"); put("p/b.json", "1"); put("p/2020/m.json", "1"); put("q/x.json", "1")
commit("add")
os.remove(f"{repo}/p/a.json"); os.remove(f"{repo}/q/x.json"); commit("delete a, x")
put("p/a.json", "2"); commit("re-add a")
os.makedirs(f"{repo}/p/2021"); os.rename(f"{repo}/p/2020/m.json", f"{repo}/p/2021/m.json"); commit("move m")
agree("a first build matches git")
store = d._store_path(repo, "p")
assert store.exists() and str(store).startswith(git("rev-parse", "--absolute-git-dir")), store

os.remove(f"{repo}/p/a.json"); os.remove(f"{repo}/p/b.json"); put("p/c.json", "1")
newest = commit("delete a, b")
agree("a later HEAD extends the map")
import json
assert json.loads(store.read_text())["tip"] == newest, "the extended map was not stored"

git("checkout", "-q", "HEAD~2")
agree("an older HEAD drops the deletions it cannot reach")
os.remove(f"{repo}/p/b.json"); commit("a side commit deleting b")
agree("a diverged HEAD adds its own deletions")
assert json.loads(store.read_text())["tip"] == newest, "a behind/diverged HEAD rewrote the map"

git("checkout", "-q", "--orphan", "rewritten"); git("rm", "-rqf", ".")
put("p/c.json", "9"); commit("unrelated root")
os.remove(f"{repo}/p/c.json"); commit("delete c")
agree("history sharing nothing with the stored tip rebuilds the map")

store.write_text("{not json")
agree("an unreadable map is rebuilt")
sys.exit(1 if fails else 0)
PY
