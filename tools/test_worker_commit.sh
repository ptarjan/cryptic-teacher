#!/bin/bash
# Does worker_commit commit only its own paths, and say why when it cannot?
#
#     bash tools/test_worker_commit.sh
#
# worker_commit is read out of tools/puzzle_worker.sh into a scratch repo.
# 1. A sibling's file is staged in the shared index (as a git outside
#    ct-index.lock leaves it); the commit must hold only its own file, and the
#    sibling's stays staged, uncommitted.
# 2. A held index.lock that clears within the retries: the commit lands.
# 3. A commit with nothing staged (-q makes git say nothing): the alert must
#    carry a reason, not end at its colon.
# 4. git killed by SIGBUS (exit 135) is tried again and the commit lands.
# 5. Three kills in a row: the alert comes only after the third try.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/tools/puzzle_worker.sh"
block="$(sed -n '/^worker_commit() {/,/^}/p' "$SCRIPT")"
if [ -z "$block" ]; then echo "FAIL tools/puzzle_worker.sh no longer defines worker_commit()"; exit 1; fi
eval "$block"
fails=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails + 1)); }

ALERTS=""
alert() { ALERTS="$ALERTS$*"$'\n'; }
index_unlock() { :; }
clear_stale_index_lock() { rm -f "$(git rev-parse --git-path index.lock)"; }
python3() { echo "Trailer: test"; }   # provenance.py trailer
WORKER_JOB="test burn"
tree="$(mktemp -d)"
mkdir -p "$tree/tools"
printf '#!/bin/sh\nexit 0\n' >"$tree/tools/push_puzzle_commit.sh"
chmod +x "$tree/tools/push_puzzle_commit.sh"
cd "$tree" || exit 1
git init -q
git config user.name "worker commit test"
git config user.email "worker-commit-test@example.invalid"
git add tools
git commit -q -m base

# 1. a sibling's staged file is not swept in
echo a >azed-2778.json
echo b >book-12035.json
git add azed-2778.json book-12035.json
worker_commit "Annotate book-12035" book-12035.json
files="$(git show --name-only --format= HEAD | tr '\n' ' ')"
[ "$files" = "book-12035.json " ] && ok "commit holds only its own file" || bad "commit held: $files"
[ "$(git diff --cached --name-only)" = "azed-2778.json" ] && ok "the sibling's file is still staged, uncommitted" ||
  bad "sibling staged state: $(git diff --cached --name-only)"
git reset -q -- azed-2778.json
rm -f azed-2778.json

# 2. a lock held at the first try is cleared and the commit retried
echo c >p3.json
git add p3.json
: >"$(git rev-parse --git-path index.lock)"
worker_commit "Annotate p3" p3.json
[ "$(git log -1 --format=%s)" = "Annotate p3" ] && ok "a held index.lock is waited out, then the commit lands" ||
  bad "after a held lock HEAD is: $(git log -1 --format=%s); alerts: $ALERTS"

# 3. nothing staged: the refusal carries a reason
ALERTS=""
worker_commit "Annotate p3 again" p3.json
case "$ALERTS" in
  *"could not commit Annotate p3 again"*": "?*) ok "an empty refusal still carries a reason: ${ALERTS:0:200}" ;;
  *) bad "alert has no reason: '$ALERTS'" ;;
esac
[ -n "$(printf '%s' "$ALERTS" | sed 's/.*fix\(ed\)*: //' | tr -d '[:space:]')" ] && ok "text after the colon is not empty" || bad "text after the colon is empty"

# 4. a git killed by SIGBUS (135) is tried again; each retry logs the signal
# git runs in a $(...) subshell, so the kill count lives in a file.
SIGNAL_RETRY_WAIT=0
kills="$tree/kills"
git() {
  if [ "$1" = commit ] && [ "$(cat "$kills")" -gt 0 ]; then
    echo $(($(cat "$kills") - 1)) >"$kills"
    return 135
  fi
  command git "$@"
}
echo c4 >p4.json
command git add p4.json
echo 2 >"$kills"
ALERTS=""
err="$(worker_commit "Annotate p4" p4.json 2>&1 >/dev/null)"
[ "$(command git log -1 --format=%s)" = "Annotate p4" ] && ok "two SIGBUS kills, then the commit lands" ||
  bad "after two kills HEAD is: $(command git log -1 --format=%s); alerts: $ALERTS"
[ "$(printf '%s\n' "$err" | grep -c 'killed by SIGBUS')" = 2 ] && ok "each retry logs one line naming SIGBUS" ||
  bad "stderr was: $err"

# 5. three kills in a row: failure is reported only after the last try
echo c5 >p5.json
command git add p5.json
echo 3 >"$kills"
ALERTS=""
worker_commit "Annotate p5" p5.json 2>/dev/null
[ "$(command git log -1 --format=%s)" = "Annotate p4" ] && ok "three kills: nothing committed" || bad "HEAD moved after three kills"
case "$ALERTS" in
  *"could not commit Annotate p5"*"exited 135"*) ok "the alert comes only after the third try" ;;
  *) bad "alert: '$ALERTS'" ;;
esac
[ "$(cat "$kills")" = 0 ] && ok "exactly three tries were made" || bad "kills left: $(cat "$kills")"
unset -f git

cd / || exit 1
rm -rf "$tree"
[ "$fails" = 0 ] && echo "worker_commit: all checks passed" || { echo "$fails failed"; exit 1; }
