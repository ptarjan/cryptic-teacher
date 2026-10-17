#!/usr/bin/env python3
# A commit made from a stale tree is refused; ordinary edits, deletions and reverts are not.
#
#     python3 tools/test_clobber_guard.py
#
# Rebuilds 2026-10-16's 456d5a0397 in a scratch repo: history of 10 files grows
# over four commits, then a commit whose parent is current carries the OLD files
# plus one real edit. tools/clobber_guard.py must refuse it, name the old commit,
# and pass a normal edit, a small deletion, a "Revert" and CLOBBER_OK=1.
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clobber_guard as G

fails = 0
def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok

repo = tempfile.mkdtemp()
os.chdir(repo)
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
os.environ.update(env)
os.environ.pop("CLOBBER_OK", None)

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()

def commit(msg, files, drop=()):
    for name, text in files.items():
        os.makedirs(os.path.dirname(name) or ".", exist_ok=True)
        open(name, "w").write(text)
    for name in drop:
        os.remove(name)
    git("add", "-A")
    git("commit", "-q", "-m", msg)
    return git("rev-parse", "HEAD")

git("init", "-q", "-b", "master")
commit("seed", {f"puzzles/p{i}.json": "v0\n" for i in range(10)} | {"tools/a.py": "a0\nb0\n", "tools/b.py": "x\n"})
old = commit("files filed", {f"puzzles/p{i}.json": "v1\n" for i in range(10)})
commit("burn edit", {"tools/a.py": "a0\nb1\n"})
commit("more filed", {f"puzzles/q{i}.json": "q\n" for i in range(6)})
head = git("rev-parse", "HEAD")

# The stale commit: the seed's files (old tree), one real edit, parent = head.
os.environ["GIT_INDEX_FILE"] = os.path.join(repo, "stale-index")
git("read-tree", git("rev-parse", "master~3"))
blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], input="x\nocr\n", capture_output=True,
                      text=True, check=True).stdout.strip()
git("update-index", "--cacheinfo", f"100644,{blob},tools/b.py")
tree = git("write-tree")
del os.environ["GIT_INDEX_FILE"]
stale = git("commit-tree", tree, "-p", head, "-m", "OCR change")
check("a stale-tree commit is refused", G.check(stale) is not None)
check("it names the older commit it rolled back to", G.check(stale) is not None and git("rev-parse", "--short", "master~3") in G.check(stale))

# The same real edit made on the current tree is fine.
fine = commit("OCR change", {"tools/b.py": "x\nocr\n"})
check("the same edit on the current tree passes", G.check(fine) is None)
many = commit("File six", {f"puzzles/r{i}.json": "r\n" for i in range(6)})
check("a commit adding files passes", G.check(many) is None)
gone = commit("Drop two", {}, drop=["puzzles/r0.json", "puzzles/r1.json"])
check("a small deletion passes", G.check(gone) is None)
check("five puzzles deleted outright pass (nothing older to roll back to)",
      G.check(commit("Drop q", {}, drop=[f"puzzles/q{i}.json" for i in range(5)])) is None)

# Rolling back on purpose.
rev = git("commit-tree", git("rev-parse", stale + "^{tree}"), "-p", git("rev-parse", "HEAD"), "-m", "Revert the burn's filing")
check("a Revert subject passes", G.check(rev) is None)
os.environ["CLOBBER_OK"] = "1"
check("CLOBBER_OK=1 passes", G.check(stale) is None)
os.environ.pop("CLOBBER_OK")

# Via the command line.
r = subprocess.run([sys.executable, os.path.join(HERE, "clobber_guard.py"), stale], capture_output=True, text=True)
check("the command exits 4 and says why", r.returncode == 4 and "stale tree" in r.stderr)
r = subprocess.run([sys.executable, os.path.join(HERE, "clobber_guard.py"), fine], capture_output=True, text=True)
check("the command exits 0 on a good commit", r.returncode == 0)
sys.exit(1 if fails else 0)
