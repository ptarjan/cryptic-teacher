#!/bin/bash
# Does tools/push_puzzle_commit.sh publish a commit while another process keeps
# writing into the same working tree, where fetch + rebase --autostash + push
# fails? The burn (tools/prereset_backfill.sh) commits and pushes each puzzle
# while the rest of its wave is still writing into that tree.
#
#     bash tools/test_push_puzzle_commit.sh
#
# Each round moves origin from a second clone, commits one puzzle in the burn's
# clone and pushes it, with a sibling rewriting a tracked file in a tight loop.
# The old push's failures are printed to show the race, but not asserted: it is
# timing-dependent, and a fast runner may never lose it. The new push must
# never fail, must publish every puzzle, must leave HEAD and
# the sibling's file alone, and must not revert what the other clone pushed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
push="$here/push_puzzle_commit.sh"
rounds="${ROUNDS:-25}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

g() { git -c user.name=t -c user.email=t@t -c advice.detachedHead=false "$@"; }
# The script under test runs plain git, which CI gives no identity to commit with.
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
git init -q --bare -b master "$tmp/origin.git"
g clone -q "$tmp/origin.git" "$tmp/seed" 2>/dev/null
mkdir -p "$tmp/seed/puzzles/s/2026"
echo 0 >"$tmp/seed/puzzles/s/2026/sibling.json"
echo 0 >"$tmp/seed/other.txt"
g -C "$tmp/seed" add -A && g -C "$tmp/seed" commit -qm seed && g -C "$tmp/seed" push -q origin HEAD:master
g clone -q "$tmp/origin.git" "$tmp/other"
g clone -q "$tmp/origin.git" "$tmp/burn"
g -C "$tmp/burn" checkout -q --detach

old_push() {
  git fetch -q origin master && g rebase -q --autostash origin/master &&
    git push -q origin HEAD:master
}

# $1 old|new. Prints how many rounds failed.
run() {
  local how="$1" i fails=0 wedged=0
  cd "$tmp/burn" || exit 1
  ( while :; do echo "$RANDOM" >puzzles/s/2026/sibling.json; sleep 0.01; done ) >/dev/null 2>&1 &
  writer=$!
  for i in $(seq "$rounds"); do
    echo "$how $i" >>"$tmp/other/other.txt"
    g -C "$tmp/other" commit -qam "other $how $i"
    g -C "$tmp/other" pull -q --rebase origin master >/dev/null 2>&1
    g -C "$tmp/other" push -q origin HEAD:master 2>/dev/null
    echo "{}" >"puzzles/s/2026/$how-$i.json"
    g add -- "puzzles/s/2026/$how-$i.json"
    g commit -qm "Annotate $how-$i" -- "puzzles/s/2026/$how-$i.json"
    if [ "$how" = old ]; then
      old_push >>"$tmp/old.err" 2>&1 || fails=$((fails + 1))
      # Unwedge, with the writer paused, so the next round can try again; its
      # rebase carries this round's commit along.
      kill -STOP "$writer"
      if [ -d "$(git rev-parse --git-dir)/rebase-merge" ]; then
        wedged=$((wedged + 1))
        g rebase --abort >/dev/null 2>&1 || rm -rf "$(git rev-parse --git-dir)/rebase-merge"
      fi
      [ -n "$(git stash list)" ] && g stash pop -q >/dev/null 2>&1
      g checkout -q -- puzzles/s/2026/sibling.json
      kill -CONT "$writer"
    else
      "$push" >>"$tmp/new.err" 2>&1 || fails=$((fails + 1))
    fi
  done
  kill "$writer"; wait "$writer" 2>/dev/null
  [ "$wedged" = 0 ] || echo "  ($wedged of those left rebase-merge/ behind)" >&2
  echo "$fails"
}

rc=0
old_fails=$(run old)
echo "old push (fetch, rebase --autostash, push): $old_fails of $rounds rounds failed, e.g.:"
grep -E "^(error|fatal)" "$tmp/old.err" | sort | uniq -c | sort -rn | head -4 | sed 's/^/    /' 
[ "$old_fails" -gt 0 ] || echo "  (the old push never lost the race this time; the checks below still hold)"

g -C "$tmp/burn" fetch -q origin master
g -C "$tmp/burn" reset -q --hard origin/master
g -C "$tmp/burn" stash clear
head_before=$(git -C "$tmp/burn" rev-parse HEAD)
new_fails=$(run new)
echo "new push (tools/push_puzzle_commit.sh):        $new_fails of $rounds rounds failed"
[ "$new_fails" = 0 ] || { echo "FAIL: push_puzzle_commit.sh failed with a sibling writing:"; sort "$tmp/new.err" | uniq -c | sort -rn | head -5; rc=1; }

cd "$tmp/burn" || exit 1
git fetch -q origin master
missing=0
for i in $(seq "$rounds"); do
  git cat-file -e "origin/master:puzzles/s/2026/new-$i.json" 2>/dev/null || missing=$((missing + 1))
  git cat-file -p origin/master:other.txt | grep -x "new $i" >/dev/null || { echo "FAIL: other clone's line $i was reverted"; rc=1; }
done
[ "$missing" = 0 ] || { echo "FAIL: $missing puzzles never reached origin/master"; rc=1; }
[ "$(git rev-list --count "$head_before..HEAD")" = "$rounds" ] ||
  { echo "FAIL: HEAD moved: the push touched the local branch"; rc=1; }
git diff --quiet HEAD -- puzzles/s/2026/sibling.json &&
  { echo "FAIL: the sibling's uncommitted write was swept away"; rc=1; }
[ -d "$(git rev-parse --git-dir)/rebase-merge" ] && { echo "FAIL: a rebase was left behind"; rc=1; }
[ -z "$(git stash list)" ] || { echo "FAIL: something was stashed"; rc=1; }

# The quiet-tree catch-up the burn does after a wave: the local copies drop out.
g rebase -q --autostash origin/master >/dev/null 2>&1
[ "$(git rev-list --count origin/master..HEAD)" = 0 ] ||
  { echo "FAIL: after the rebase, local commits were not recognised as already pushed"; rc=1; }

# An upstream edit to the same file conflicts; it must be refused, not reverted.
echo "{}" >puzzles/s/2026/clash.json && g add -A -- puzzles && g commit -qm clash-base -- puzzles/s/2026/clash.json
git push -q origin HEAD:master
g -C "$tmp/other" pull -q --rebase origin master 2>/dev/null
echo '{"a":1}' >"$tmp/other/puzzles/s/2026/clash.json"
g -C "$tmp/other" commit -qam "other edits clash" && g -C "$tmp/other" push -q origin HEAD:master
echo '{"b":2}' >puzzles/s/2026/clash.json
g commit -qm "Annotate clash" -- puzzles/s/2026/clash.json
if "$push" 2>/dev/null; then
  echo "FAIL: a conflicting edit was pushed over the other clone's"; rc=1
fi
git fetch -q origin master
[ "$(git cat-file -p origin/master:puzzles/s/2026/clash.json)" = '{"a":1}' ] ||
  { echo "FAIL: origin's clash.json changed"; rc=1; }

# A promotion racing a re-read of its clues-only file (the book reader re-writes
# clues_only/X.json while the burn deletes it and files puzzles/.../X.json) is a
# modify/delete conflict: the promotion must still land, the clues-only copy
# must stay gone, and the re-read's text must reach the puzzle only where the
# filed clue is still the old reading.
# $1 file, $2..: across clue texts then "|" then down clue texts.
clues_only() {
  python3 - "$@" <<'EOF'
import json, sys
path, rest = sys.argv[1], sys.argv[2:]
cut = rest.index("|")
clue = lambda t: {"clue": {"text": t, "enumeration": "4"}, "length": 4}
rec = {"id": "bk-1", "clues": {"across": [clue(t) for t in rest[:cut]],
                              "down": [clue(t) for t in rest[cut + 1:]]}}
open(path, "w", encoding="utf-8").write(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
EOF
}
# $1 file, $2..: "<number><a|d>=<text>[=<definition>]".
promoted() {
  python3 - "$@" <<'EOF'
import json, sys
entries = []
for spec in sys.argv[2:]:
    key, text, *defn = spec.split("=")
    e = {"number": int(key[:-1]), "direction": {"a": "across", "d": "down"}[key[-1]],
         "clue": {"text": text, "enumeration": "4"}}
    if defn:
        e["annotation"] = {"definitions": [{"text": defn[0], "at": text.index(defn[0])}]}
    entries.append(e)
open(sys.argv[1], "w", encoding="utf-8").write(
    json.dumps({"id": "bk-1", "entries": entries}, indent=1, ensure_ascii=False) + "\n")
EOF
}
clue_of() {  # $1 rev, $2 number+direction letter
  git cat-file -p "$1:puzzles/bk/2009/bk-1.json" | python3 -c "
import json,sys; k=sys.argv[1]
print([e['clue']['text'] for e in json.load(sys.stdin)['entries']
       if f\"{e['number']}{e['direction'][0]}\" == k][0])" "$2"
}
race_setup() {  # a fresh clues-only bk-1 on origin, both clones on it
  cd "$tmp/burn" || exit 1
  git fetch -q origin master && g reset -q --hard origin/master
  git rm -rq --ignore-unmatch puzzles/bk clues_only >/dev/null
  mkdir -p clues_only/bk
  clues_only clues_only/bk/bk-1.json "Fish’s tale" "Odd shrib" "Bird’s nest" "|" "Crow’s feet"
  g add -A -- clues_only puzzles && g commit -qm "hold bk-1" -- clues_only puzzles
  git push -q origin HEAD:master
  g -C "$tmp/other" fetch -q origin master && g -C "$tmp/other" reset -q --hard origin/master
}
# The re-read straightens quotes in 1a, 7a (where the filed clue still has the
# old text) and 2d (filed with a fix), and leaves 4a's OCR slip alone.
reread() { clues_only "$1" "Fish's tale" "Odd shrib" "Bird's nest" "|" "Crow's feet"; }
promote() {  # in $1's tree
  mkdir -p "$1/puzzles/bk/2009" && git -C "$1" rm -q clues_only/bk/bk-1.json
  # 7a's annotation names "Bird’s" as its definition, which the re-read loses.
  promoted "$1/puzzles/bk/2009/bk-1.json" "1a=Fish’s tale" "4a=Odd shrub" \
    "7a=Bird’s nest=Bird’s" "2d=Crow's feet!"
  g -C "$1" add puzzles/bk/2009/bk-1.json
}

race_setup
reread "$tmp/other/clues_only/bk/bk-1.json"
g -C "$tmp/other" commit -qam "Read bk (so far)" && g -C "$tmp/other" push -q origin HEAD:master
promote "$tmp/burn"
g commit -qm "Annotate bk-1" -- puzzles/bk clues_only/bk
"$push" 2>"$tmp/race.err" || { echo "FAIL: a promotion racing a re-read was not pushed:"; cat "$tmp/race.err"; rc=1; }
git fetch -q origin master
git cat-file -e origin/master:clues_only/bk/bk-1.json 2>/dev/null &&
  { echo "FAIL: the re-read resurrected clues_only/bk/bk-1.json"; rc=1; }
[ "$(clue_of origin/master 1a)" = "Fish's tale" ] || { echo "FAIL: 1a did not take the re-read: $(clue_of origin/master 1a)"; rc=1; }
[ "$(clue_of origin/master 4a)" = "Odd shrub" ] || { echo "FAIL: 4a lost the annotator's fix"; rc=1; }
[ "$(clue_of origin/master 7a)" = "Bird’s nest" ] || { echo "FAIL: 7a took a re-read its annotation does not fit"; rc=1; }
[ "$(clue_of origin/master 2d)" = "Crow's feet!" ] || { echo "FAIL: 2d lost the annotator's fix"; rc=1; }
grep -q "7a: kept" "$tmp/race.err" || { echo "FAIL: the dropped 7a re-read was not reported"; rc=1; }

# The reverse: the reader's commit re-writes a clues-only file origin has
# promoted. The promotion stands; the re-read must not bring the file back.
race_setup
promote "$tmp/other"
g -C "$tmp/other" commit -qm "Annotate bk-1" && g -C "$tmp/other" push -q origin HEAD:master
reread clues_only/bk/bk-1.json
g commit -qm "Read bk (so far)" -- clues_only/bk/bk-1.json
"$push" 2>"$tmp/race.err" || { echo "FAIL: a re-read racing a promotion was refused:"; cat "$tmp/race.err"; rc=1; }
git fetch -q origin master
git cat-file -e origin/master:clues_only/bk/bk-1.json 2>/dev/null &&
  { echo "FAIL: a re-read resurrected a promoted puzzle's clues_only file"; rc=1; }
[ "$(clue_of origin/master 1a)" = "Fish's tale" ] || { echo "FAIL: reverse: 1a did not take the re-read"; rc=1; }
[ "$(clue_of origin/master 4a)" = "Odd shrub" ] || { echo "FAIL: reverse: 4a lost the annotator's fix"; rc=1; }

# An annotation whose puzzle origin changed in a field the commit also touched
# (10-13: genius files re-dated / given setters on master while the burn
# annotated them) is re-applied onto origin's file, not refused: origin's
# fields stand, the commit's annotation lands.
ann_puzzle() {  # $1 file, $2 date, $3 setter or "", $4 annotation of 1a or ""
  python3 - "$@" <<'EOF'
import json, sys
f, date, setter, ann = sys.argv[1:5]
e1 = {"number": 1, "direction": "across", "clue": {"text": "Fish tale"}, "solution": "COD"}
if ann:
    e1["annotation"] = {"definition": ann}
p = {"id": "nn-1", "date": date, "entries": [e1, {"number": 2, "direction": "down",
     "clue": {"text": "Odd shrub"}, "solution": "BUSH"}]}
if setter:
    p["setter"] = setter
if ann:
    p["annotatedBy"] = ["model"]
open(f, "w").write(json.dumps(p, indent=1) + "\n")
EOF
}
mkdir -p puzzles/nn
ann_puzzle puzzles/nn/nn-1.json 2011-07-01 "" ""
g add puzzles/nn && g commit -qm "File nn-1" -- puzzles/nn && "$push" 2>/dev/null
g -C "$tmp/other" pull -q --rebase origin master 2>/dev/null
ann_puzzle "$tmp/other/puzzles/nn/nn-1.json" 2011-07-18 Setter ""
g -C "$tmp/other" commit -qam "Re-date nn-1" && g -C "$tmp/other" push -q origin HEAD:master
ann_puzzle puzzles/nn/nn-1.json 2011-07-02 "" "Fish"
g commit -qm "Annotate nn-1" -- puzzles/nn/nn-1.json
"$push" 2>"$tmp/reapply.err" || { echo "FAIL: an annotation was refused over origin's re-date:"; cat "$tmp/reapply.err"; rc=1; }
git fetch -q origin master
python3 - <<EOF || rc=1
import json, subprocess
p = json.loads(subprocess.check_output(["git", "show", "origin/master:puzzles/nn/nn-1.json"]))
bad = []
if p.get("date") != "2011-07-18": bad.append(f"origin's date lost: {p.get('date')}")
if p.get("setter") != "Setter": bad.append("origin's setter lost")
if (p["entries"][0].get("annotation") or {}).get("definition") != "Fish": bad.append("annotation not re-applied")
if p.get("annotatedBy") != ["model"]: bad.append("annotatedBy not carried")
for b in bad: print("FAIL: reapply:", b)
raise SystemExit(1 if bad else 0)
EOF
grep -q "kept origin's value" "$tmp/reapply.err" || { echo "FAIL: reapply did not report the field origin kept"; rc=1; }

[ "$rc" = 0 ] && echo "PASS"
exit "$rc"
