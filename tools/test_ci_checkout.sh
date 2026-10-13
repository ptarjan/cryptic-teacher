#!/usr/bin/env bash
# The deploy's checkout (.github/workflows/pages.yml, build/Check out) run
# twice against a local origin: once cold, then on what Restore the git store
# brings back, where it must fetch only what the new commit added rather than
# the whole tree again (that refetch was ~58s a run). Then that every cache
# the build restores is saved again with the same paths and key, and that
# tools/trim_codeql_caches.py keeps the newest CodeQL entry per language and
# touches nothing else, and that the site is uploaded stored, not deflated.
set -euo pipefail
trap 'echo "test_ci_checkout: failed at line $LINENO: $BASH_COMMAND" >&2' ERR
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
wf=.github/workflows/pages.yml

python3 - "$wf" "$tmp" <<'EOF'
import sys, yaml
wf = yaml.safe_load(open(sys.argv[1]))
steps = {s.get("name"): s for s in wf["jobs"]["build"]["steps"]}
open(f"{sys.argv[2]}/checkout.sh", "w").write(steps["Check out"]["run"])
open(f"{sys.argv[2]}/paths", "w").write(steps["Restore the git store"]["with"]["path"])
# Deflate was the upload's bottleneck (65s at 6, 40s at 1) on an artifact
# that is half PNG: stored, it is bound by the network.
if steps["Upload the site"]["with"].get("compression-level") != 0:
    sys.exit("test_ci_checkout: Upload the site should be stored (compression-level: 0)")
# Every restore has its save: same paths (part of the cache version), same key.
for name, s in steps.items():
    if not name or "actions/cache/restore" not in s.get("uses", ""):
        continue
    save = steps.get(name.replace("Restore", "Save", 1))
    if not save or "actions/cache/save" not in save.get("uses", ""):
        sys.exit(f"test_ci_checkout: {name} has no {name.replace('Restore', 'Save', 1)} step")
    for k in ("path", "key"):
        if save["with"][k] != s["with"][k]:
            sys.exit(f"test_ci_checkout: {name} and its save differ in {k}")
    if "!cancelled()" not in str(save.get("if", "")):
        sys.exit(f"test_ci_checkout: {save['name']} would be skipped by an earlier failed step")
EOF

g() { git -c user.name=t -c user.email=t@t -c init.defaultBranch=master "$@"; }
g init -q "$tmp/origin"
for i in $(seq 1 200); do head -c 2000 /dev/urandom | base64 > "$tmp/origin/f$i"; done
g -C "$tmp/origin" add .
g -C "$tmp/origin" commit -qm one
a=$(git -C "$tmp/origin" rev-parse HEAD)
echo changed >> "$tmp/origin/f1"
g -C "$tmp/origin" commit -qam two
b=$(git -C "$tmp/origin" rev-parse HEAD)

run() {  # run <dir> <sha>
  (cd "$1" && GITHUB_SERVER_URL="file://$tmp" GITHUB_REPOSITORY=origin GITHUB_SHA="$2" TOKEN= \
     bash -e "$tmp/checkout.sh" >/dev/null 2>&1) || { echo "test_ci_checkout: the checkout failed in $1"; exit 1; }
  [ "$(git -C "$1" rev-parse HEAD)" = "$2" ] || { echo "test_ci_checkout: $1 is not at $2"; exit 1; }
  diff -rq --exclude=.git "$tmp/origin" "$1" >/dev/null || { echo "test_ci_checkout: $1 differs from the commit"; exit 1; }
}
objects() { git -C "$1" count-objects -v | awk '/^(count|in-pack):/ {n += $2} END {print n}'; }

mkdir "$tmp/cold"
git -C "$tmp/origin" checkout -q "$a"
run "$tmp/cold" "$a"
git -C "$tmp/origin" checkout -q master

# What the cache carries, and nothing else.
mkdir -p "$tmp/warm"
while read -r p; do
  [ -n "$p" ] && [ -e "$tmp/cold/$p" ] || continue  # the cache skips a missing path too
  mkdir -p "$tmp/warm/$(dirname "$p")"
  cp -r "$tmp/cold/$p" "$tmp/warm/$p"
done < "$tmp/paths"
before=$(objects "$tmp/cold")  # the warm store is a copy of it
run "$tmp/warm" "$b"
added=$(( $(objects "$tmp/warm") - before ))
# The new commit, its tree and the one changed blob: 3. A refetch is ~200.
[ "$added" -le 5 ] || { echo "test_ci_checkout: the warm fetch took $added objects, not just the change"; exit 1; }

# A store whose refs/ct/base is missing still checks out (just slower).
mkdir -p "$tmp/noref/.git"
cp -r "$tmp/cold/.git/objects" "$tmp/noref/.git/"
run "$tmp/noref" "$b"

picked=$(printf '%s\t%s\t%s\n' \
  1 codeql-overlay-base-database-1-aaa-python-2.27.2-s1-1-1 2026-10-13T09:00:00Z \
  2 codeql-overlay-base-database-1-aaa-python-2.27.2-s2-2-1 2026-10-13T09:10:00Z \
  3 codeql-overlay-base-database-1-bbb-javascript-2.27.2-s1-1-1 2026-10-13T09:00:00Z \
  4 codeql-overlay-base-database-1-aaa-python-2.27.3-s3-3-1 2026-10-13T09:20:00Z \
  5 og-cards-s1 2026-10-13T08:00:00Z \
  | python3 tools/trim_codeql_caches.py --pick | sort | tr '\n' ' ')
[ "$picked" = "1 2 " ] || { echo "test_ci_checkout: trim picked '$picked', wanted '1 2 '"; exit 1; }
echo "test_ci_checkout: all passed"
