#!/bin/bash
# Does every `claude -p` in tools/ name its conversation, so a run stopped from
# outside is resumed rather than bought again?
#
#     bash tools/test_session_ids.sh
#
# Paul's rule: always resume when interrupted. A run that is killed (a restart,
# a unit's time limit) has its transcript on disk; only a run that was given a
# session id up front can be resumed from it. So every call site passes its
# session flags on the call line itself: "${sess[@]}" in shell, built by
# worker_annotate (tools/puzzle_worker.sh) or session_args
# (tools/claude_session.sh), or --session-id / --resume in Python.
#
# Exempt, by name: the one-shot judges whose whole output is one tool-less
# reply on stdout. Killed, they have nothing to resume, and each one's loop
# already skips the batches that have a score.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

EXEMPT=" tools/grade_clues_judge.sh tools/favourite_grading.sh tools/author_trial.py "

echo "every claude -p call site names its conversation"
sites=0
unnamed=""
while IFS=: read -r file line text; do
  sites=$((sites + 1))
  case "$EXEMPT" in *" $file "*) continue ;; esac
  # shellcheck disable=SC2016  # the literal text of the call
  case "$file" in
    *.sh) grep -q '"\${sess\[@\]}"' <<<"$text" ;;
    *) grep -q -e '--session-id' -e '--resume' <<<"$text" ;;
  esac || unnamed="$unnamed $file:$line"
done < <(git ls-files -- 'tools/*.sh' 'tools/*.py' | grep -v '^tools/test_' |
         xargs grep -n -e '^[^#]*claude -p\b' -e '"claude", *"-p"' |
         grep -v '^[^:]*\.py:[0-9]*:.*claude -p' )
check "call sites without a session id" "$unnamed" ""
check "the call sites were found at all" "$([ "$sites" -ge 5 ] && echo yes || echo "no ($sites)")" "yes"

echo "each exempt file still holds a call, so the list cannot outlive its reason"
for f in $EXEMPT; do
  check "$f calls claude -p" "$(grep -c -e '^[^#]*claude -p\b' -e '"claude", *"-p"' "$f" | awk '{print ($1 > 0)}')" "1"
done

echo "session_args names a fresh run and resumes a stopped one"
stub=$(mktemp -d)
trap 'rm -rf "$stub"' EXIT
export CLAUDE_CONFIG_DIR="$stub/cfg"
. tools/claude_session.sh
session_id() { echo sid-new; }
task="the task" sess=()
session_args "$stub/x.sid" sess task
check "a fresh run is named and recorded" "${sess[*]} $(cat "$stub/x.sid")" "--session-id sid-new sid-new"
check "its task is the task" "$task" "the task"
mkdir -p "$CLAUDE_CONFIG_DIR/projects/elsewhere"
: >"$CLAUDE_CONFIG_DIR/projects/elsewhere/sid-new.jsonl"
session_args "$stub/x.sid" sess task
check "a stopped run is resumed" "${sess[*]}" "--resume sid-new"
check "with a note, then the task" "$(head -c 21 <<<"$task") $(tail -1 <<<"$task")" "You were stopped from the task"
touch -t "$(date -d '2 days ago' +%Y%m%d%H%M 2>/dev/null || date -v-2d +%Y%m%d%H%M)" "$stub/x.sid"
task="the task"
session_args "$stub/x.sid" sess task
check "a day-old one starts fresh" "${sess[*]} $task" "--session-id sid-new the task"

if [ "$fails" -gt 0 ]; then echo "session ids: $fails FAILED"; exit 1; fi
echo "session ids: all checks passed"
