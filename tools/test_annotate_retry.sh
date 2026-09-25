#!/bin/bash
# Does a failed annotation resume, or does it start over and pay twice?
#
# The retry in daily_update.sh only ever runs when a nightly job is already
# going wrong, which is the worst place to find out it was wired up wrong. So
# this drives it with a fake `claude`: the blocks under test are READ OUT OF
# daily_update.sh by their own first and last lines rather than copied here, so
# a copy cannot drift away from the thing that runs at 06:15.
#
#     bash tools/test_annotate_retry.sh
#
# Two mechanisms, and both of them exist to stop the same conversation being
# bought twice. The first is the retry: a run cut off for overrunning the
# output ceiling must come back with --resume and the SAME session id, because
# everything it had read and worked out is in that conversation and nowhere
# else.
#
# The second is the handover from the cold solve: a grid solved an hour earlier
# was solved by deriving every answer and the wordplay that reached it, which
# is exactly what the annotation has to write down. So the annotation carries
# on in the solve's conversation — but only when there is one, and never by
# re-reading answers from
# memory, because the solve transcript ends BEFORE apply_solution.py wrote the
# fill into the file.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

block=$(awk '/^      ann_sid=\$\(session_id\)/,/^      done$/' tools/daily_update.sh)
# The two halves of the cold solve that the annotation depends on: the call
# that names the conversation, and the branch that decides whether tonight
# remembers it.
solve_call=$(awk '/^    solve_sid=\$\(session_id\)/,/^      --max-turns 120 /' tools/daily_update.sh)
solve_record=$(awk '/^    if \[ "\$applied" -eq 0 \]; then$/,/^    fi$/' tools/daily_update.sh)
solve_helper=$(grep '^solve_session_of() ' tools/daily_update.sh)
# solve_record calls has_date, which daily_update.sh defines at the top of the
# file and so outside every range read above. Read it out too — not to run it,
# but so that renaming or deleting it fails here by name, rather than becoming a
# command that is simply not there and takes the queue's else branch in silence.
has_date_def=$(awk '/^has_date\(\) {/,/^}$/' tools/daily_update.sh)
for name in block solve_call solve_record solve_helper has_date_def; do
  [ -n "${!name}" ] ||
    { echo "FAIL: the $name block is no longer where this test reads it from"; exit 1; }
done

stub=$(mktemp -d)
trap 'rm -rf "$stub"' EXIT
# A claude that records how it was called and fails the way $MODE says. It also
# writes the transcript for any conversation it is told to open, because that
# file is the whole of what session_exists looks for: a run that died had one,
# and a run that never happened did not.
cat > "$stub/claude" <<'STUB'
#!/bin/bash
n=$(cat "$CALLS/n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$CALLS/n"
printf '%s\n' "$*" >> "$CALLS/argv"
prev=""
for arg in "$@"; do
  if [ "$prev" = --session-id ] && [ -n "$arg" ]; then
    mkdir -p "$CLAUDE_CONFIG_DIR/projects/-tmp-cryptic"
    : > "$CLAUDE_CONFIG_DIR/projects/-tmp-cryptic/$arg.jsonl"
  fi
  prev="$arg"
done
if [ "$n" = 1 ] && [ -n "${MODE:-}" ]; then
  [ "$MODE" = overrun ] && echo "API Error: Claude's response exceeded the 128000 output token maximum."
  [ "$MODE" = limit ] && echo "Claude AI usage limit reached"
  # What timeout(1) exits when it kills the run, and the CLI never got to print
  # a reason — which is the whole point of the case that uses this.
  [ "$MODE" = capped ] && exit 124
  exit 1
fi
echo "done"
STUB
chmod +x "$stub/claude"
PATH="$stub:$PATH"

# Which conversations the CLI still holds. session_exists asks the filesystem,
# so this test answers it with the filesystem rather than with a stub of its
# own: an id with a transcript under here is resumable and an id without one is
# gone, which is the only difference the block is allowed to see.
transcripts() {
  rm -rf "$CLAUDE_CONFIG_DIR"
  mkdir -p "$CLAUDE_CONFIG_DIR/projects/-tmp-cryptic"
  local s
  for s in $*; do : > "$CLAUDE_CONFIG_DIR/projects/-tmp-cryptic/$s.jsonl"; done
}

run() {  # $1 = MODE ("" for a clean first run),
         # $2 = tonight's solves as daily_update.sh lists them ("id:session"),
         # $3 = the sessions the CLI still has transcripts for (default: all of them).
         # SESSION_ID_BROKEN=1 in front stands in for a generator that failed.
  CALLS=$(mktemp -d); export CALLS MODE="$1"
  export CLAUDE_CONFIG_DIR="$stub/config"
  transcripts "${3-$(printf '%s\n' ${2:-} | sed -n 's/^[^:]*://p')}"
  . tools/claude_session.sh
  [ -n "${SESSION_ID_BROKEN:-}" ] && session_id() { return 1; }
  local ANNOTATE_MODEL=opus ann_tools=Read ann_turns=80 num=test-1 run_log
  local ann_file=tools/_puzzle_test-1.json
  local ANNOTATE_MAX_MINUTES=90
  local ann_cap ann_rc ann_timeout lost_ids=""
  # Tonight's cold solves, as the real variable holds them, read by the real
  # helper — a lookup that matched the wrong puzzle is exactly how a stale
  # session would reach a grid nobody solved.
  local solve_sids="${2:-}" solve_prior
  eval "$solve_helper"
  # The variable that ends the night. The cap firing must not set it.
  local stop_reason=""
  local ann_task="Annotate." ann_sid ann_sess ann_prompt ann_ok ann_retried
  run_log=$(mktemp)
  capped=""
  record_annotate_failure() { capped="$2"; }
  # The block breaks out of its retry loop when the wall-clock cap fires, and
  # in daily_update.sh that block sits inside the loop over tonight's puzzles.
  # Give it that loop, or the case below tests a `break` that cannot mean what
  # it means in production.
  for _ in 1; do eval "$block"; done >/dev/null 2>&1
  calls=$(cat "$CALLS/n"); argv=$(cat "$CALLS/argv"); ok="$ann_ok"
  timed_out="${ann_timeout:-}"; stopped="$stop_reason"
  rm -rf "$CALLS" "$run_log"
}

resumed() { sed -n "${1}s/.*--resume \([^ ]*\).*/\1/p" <<<"$argv"; }
opened() { sed -n "${1}s/.*--session-id \([^ ]*\).*/\1/p" <<<"$argv"; }

echo "a clean run is one call and no resume"
run ""
check "calls" "$calls" "1"
check "succeeded" "${ok:-no}" "1"
check "no --resume" "$(grep -c -- --resume <<<"$argv")" "0"

echo "a usage lockout is not retried — it wants the next window, not another try"
run limit
check "calls" "$calls" "1"
check "failed" "${ok:-no}" "no"

echo "an output overrun resumes the same conversation instead of starting over"
run overrun
check "calls" "$calls" "2"
check "succeeded on the retry" "${ok:-no}" "1"
check "second call resumed the first's session" "$(resumed 2)" "$(opened 1)"
check "and it did not start a new one" "$(sed -n 2p <<<"$argv" | grep -c -- --session-id)" "0"

echo "a run that outlives the wall-clock cap is stopped, charged, and not retried"
run capped
check "calls" "$calls" "1"
check "failed" "${ok:-no}" "no"
check "charged to the puzzle" "$(grep -c 'ran past 90m' <<<"${capped:-}")" "1"

# The cap is evidence about THIS grid and nothing else, and the queue behind it
# has puzzles nobody has tried. On 2026-09-12 the cap fired on independent-12459
# and ended the run, so cryptic-30109 shipped with no hints for a reason that
# had nothing to do with it. The night ends on $stop_reason; the cap must set
# $ann_timeout instead, which is what tells the puzzle loop to move on.
echo "and the cap does not end the night — it names the puzzle, not a stop"
check "named the lost puzzle" "$(grep -c 'ran past 90m' <<<"$timed_out")" "1"
check "left the night's stop reason unset" "${stopped:-unset}" "unset"

echo "a grid solved cold tonight is annotated inside the conversation that solved it"
run "" " test-1:tonights-solve"
check "calls" "$calls" "1"
check "resumed the solve" "$(resumed 1)" "tonights-solve"
check "and opened no new conversation" "$(grep -c -- --session-id <<<"$argv")" "0"
# The solve transcript ends before apply_solution.py wrote the fill in, so a
# resumed run working from memory would annotate a grid it never saw filled.
check "sent back to the file rather than left to remember the fill" \
  "$(grep -c 'Read the file as it now stands' <<<"$argv")" "1"
check "and the file it names is the one the fill was written into" \
  "$(grep -c 'tools/_puzzle_test-1\.json' <<<"$argv")" "1"
check "with the annotation instructions still attached, not replaced" \
  "$(grep -c 'tools/annotate_prompt\.md' <<<"$argv")" "1"

echo "a puzzle nobody solved tonight opens a fresh conversation, exactly as before"
run "" " test-9:someone-elses-grid"
check "opened one of its own" "$(grep -c -- --session-id <<<"$argv")" "1"
check "with nothing to resume" "$(grep -c -- --resume <<<"$argv")" "0"
check "and did not borrow the solve of another puzzle" \
  "$(grep -c someone-elses-grid <<<"$argv")" "0"

echo "unless the CLI has dropped that conversation, and then it starts fresh"
run "" " test-1:tonights-solve" ""
check "opened one of its own" "$(grep -c -- --session-id <<<"$argv")" "1"
check "with nothing to resume" "$(grep -c -- --resume <<<"$argv")" "0"

echo "with no session id to be had, the annotation starts fresh rather than resuming nothing"
SESSION_ID_BROKEN=1 run "" " test-1:"
check "the run still happened" "$calls" "1"
check "and succeeded" "${ok:-no}" "1"
check "resuming no conversation, least of all an empty one" \
  "$(grep -c -- --resume <<<"$argv")" "0"

# --- the solve side: what it leaves behind for the annotation to find ---
solve() {  # $1 = id, $2 = applied|rejected — the applier's verdict on the fill
  local num="$1" applied=1 fill solvelog verdict ANNOTATE_MODEL=opus
  local solve_sid solve_sess
  CALLS=$(mktemp -d); export CALLS MODE=""
  export CLAUDE_CONFIG_DIR="$stub/config"
  . tools/claude_session.sh
  [ -n "${SESSION_ID_BROKEN:-}" ] && session_id() { return 1; }
  fill=$(mktemp); solvelog=$(mktemp); verdict=$(mktemp)
  eval "$solve_call"
  argv=$(cat "$CALLS/argv")
  [ "$2" = applied ] && applied=0
  eval "$solve_record" >/dev/null 2>&1
  rm -rf "$CALLS" "$fill" "$solvelog" "$verdict"
}
# A scratch ledger: a rejected solve is recorded, and never in the real one.
export FAILED_INPUTS_FILE="$stub/failed_inputs.json"
alert() { :; }
# A block read out of daily_update.sh can call anything daily_update.sh defines,
# including helpers that live outside the lines read here. Bash answers a call
# to one of those with "command not found" and a 127 — false to every `if` that
# tests it — so the block quietly takes its other branch and the failure surfaces
# somewhere else entirely. Say which name was missing instead.
# Only records the name. Bash runs this handler in a forked child, so a variable
# it set would go with that child, and the blocks are run with their output sent
# to /dev/null, so anything it printed would go there. The tally reads the file.
command_not_found_handle() { echo "$1" >> "$stub/missing"; return 127; }
# Which end of the annotation queue a solve enters is has_date's call. Every id
# below is a bare name with no puzzle file behind it, which the real has_date
# reads as dateless and sends to the back — correct for a book reprint and
# beside the point here, because these cases are about WHICH CONVERSATION a
# solve leaves behind. They run as the dated case. Both branches of the ordering
# are checked against the real lines in tools/test_solve_queue_clues.sh.
has_date() { return 0; }
eval "$solve_helper"
solve_sids=""; pending=""; solved_ok=0

echo "a solve names its conversation, and that is the name the annotation resumes"
solve test-1 applied
check "the solve call opened a named conversation" \
  "$(grep -c -- --session-id <<<"$argv")" "1"
check "and it is the one the annotation would carry on" \
  "$(solve_session_of test-1)" "$(opened 1)"
check "with the grid at the head of tonight's queue" \
  "$(grep -c '^test-1 ' <<<"$pending ")" "1"

echo "a fill the applier threw out leaves no conversation for anything to resume"
solve test-2 rejected
check "the rejected grid never reaches tonight's annotate queue" \
  "$(grep -c test-2 <<<"$pending")" "0"
check "and nothing at all is written down against its id" \
  "$(solve_session_of test-2)" ""
check "so the list still holds only the grid that worked" \
  "$(printf '%s\n' $solve_sids | wc -l | tr -d ' ')" "1"

echo "a session id the generator could not make is never passed as an empty one"
solve_sids=""
SESSION_ID_BROKEN=1 solve test-3 applied
check "the solve ran with no --session-id rather than a blank one" \
  "$(grep -c -- --session-id <<<"$argv")" "0"
check "and left the annotation nothing to resume" "$(solve_session_of test-3)" ""

# One missing name is one failure, however many times the blocks called it.
for name in $([ -f "$stub/missing" ] && sort -u "$stub/missing"); do
  echo "  FAIL: the block under test calls $name, which daily_update.sh defines"\
       "outside the lines this test reads — stub it here or read it out too"
  fails=$((fails + 1))
done
[ "$fails" = 0 ] && echo "annotate retry: all checks passed" || echo "annotate retry: $fails FAILED"
exit $((fails > 0))
