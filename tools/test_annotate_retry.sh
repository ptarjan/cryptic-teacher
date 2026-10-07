#!/bin/bash
# Does a failed annotation resume, or does it start over and pay twice?
#
# The retry in daily_update.sh only ever runs when a nightly job is already
# going wrong, which is the worst place to find out it was wired up wrong. So
# this drives it with a fake `claude`: the retry loop is READ OUT OF
# daily_update.sh by its own first and last lines rather than copied here, and
# it calls the real tools/puzzle_worker.sh, so a copy cannot drift away from the
# thing that runs at 04:45.
#
#     bash tools/test_annotate_retry.sh
#
# Two mechanisms, and both of them exist to stop the same conversation being
# bought twice. The first is the retry: a run cut off for overrunning the
# output ceiling must come back with --resume and the SAME session id, because
# everything it had read and worked out is in that conversation and nowhere
# else.
#
# The second is the handover from the cold solve: a grid solved a minute
# earlier was solved by deriving every answer and the wordplay that reached it,
# which is exactly what the annotation has to write down. So the annotation
# carries on in the solve's conversation — but only when there is one, and
# never by re-reading answers from memory, because the solve transcript ends
# BEFORE apply_solution.py wrote the fill into the file. The burn
# (tools/prereset_backfill.sh) runs the same worker; tools/test_puzzle_worker.sh
# holds both scripts to it.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
check() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    expected: $3"$'\n'"    got:      $2"; fails=$((fails + 1)); fi; }

block=$(awk '/^      ann_note=""$/,/^      done$/' tools/daily_update.sh)
[ -n "$block" ] ||
  { echo "FAIL: the retry loop is no longer where this test reads it from"; exit 1; }
. tools/puzzle_worker.sh
CLAUDE_HEADLESS=()
WORKER_MODEL=opus WORKER_EFFORT=medium WORKER_WRAP=""

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

sidfile="$stub/test-1.sid"
run() {  # $1 = MODE ("" for a clean first run),
         # $2 = what the puzzle's sid file holds ("" for no file), e.g. "abc solve"
         # $3 = the sessions the CLI still has transcripts for (default: the sid file's).
         # SESSION_ID_BROKEN=1 in front stands in for a generator that failed.
  CALLS=$(mktemp -d); export CALLS MODE="$1"
  export CLAUDE_CONFIG_DIR="$stub/config"
  rm -f "$sidfile"
  [ -n "${2:-}" ] && echo "$2" >"$sidfile"
  transcripts "${3-$(cut -d' ' -f1 <<<"${2:-}")}"
  . tools/claude_session.sh
  [ -n "${SESSION_ID_BROKEN:-}" ] && session_id() { return 1; }
  local ann_tools=Read ann_turns=80 num=test-1 run_log
  local ann_file=tools/_puzzle_test-1.json
  local ann_prompt="Annotate the cryptic crossword test-1 in this repo, whose clues and answers are in $ann_file. Follow tools/annotate_prompt.md exactly."
  local ANNOTATE_MAX_MINUTES=90
  local ann_rc ann_timeout lost_ids="" ann_sid
  # The variable that ends the night. The cap firing must not set it.
  local stop_reason=""
  local ann_note ann_ok ann_retried
  run_log=$(mktemp)
  capped=""
  record_annotate_failure() { capped="$2"; }
  annotate_alert() { :; }
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
system() { sed -n "${1}s/.*--append-system-prompt-file \([^ ]*\).*/\1/p" <<<"$argv"; }

echo "a clean run is one call and no resume"
run ""
check "calls" "$calls" "1"
check "succeeded" "${ok:-no}" "1"
check "no --resume" "$(grep -c -- --resume <<<"$argv")" "0"
check "on the annotation's own system prompt" "$(system 1)" "tools/annotate_prompt.md"

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
# has puzzles nobody has tried; ending the run there would ship the next puzzle
# with no hints for a reason that has nothing to do with it. The night ends on $stop_reason; the cap must set
# $ann_timeout instead, which is what tells the puzzle loop to move on.
echo "and the cap does not end the night — it names the puzzle, not a stop"
check "named the lost puzzle" "$(grep -c 'ran past 90m' <<<"$timed_out")" "1"
check "left the night's stop reason unset" "${stopped:-unset}" "unset"

echo "a grid just solved cold is annotated inside the conversation that solved it"
run "" "tonights-solve solve"
check "calls" "$calls" "1"
check "resumed the solve" "$(resumed 1)" "tonights-solve"
check "and opened no new conversation" "$(grep -c -- --session-id <<<"$argv")" "0"
check "with the solve's system prompt, so its cached prefix still matches" \
  "$(system 1)" "tools/solve_prompt.md"
# The solve transcript ends before apply_solution.py wrote the fill in, so a
# resumed run working from memory would annotate a grid it never saw filled.
check "sent back to the file rather than left to remember the fill" \
  "$(grep -c 'Read the file as it now stands' <<<"$argv")" "1"
check "and the file it names is the one the fill was written into" \
  "$(grep -c 'tools/_puzzle_test-1\.json' <<<"$argv")" "1"
check "with the annotation instructions still attached, not replaced" \
  "$(grep -c 'tools/annotate_prompt\.md' <<<"$argv")" "1"
check "and the conversation is marked handed over" "$(cat "$sidfile")" "tonights-solve annotating"

echo "an overrun after the handover resumes the solve's conversation on its system prompt"
run overrun "tonights-solve solve"
check "calls" "$calls" "2"
check "both in the solve's conversation" "$(resumed 1) $(resumed 2)" "tonights-solve tonights-solve"
check "on the solve's system prompt both times" "$(system 1) $(system 2)" \
  "tools/solve_prompt.md tools/solve_prompt.md"

echo "a conversation already handed over is not handed over again"
run "" "tonights-solve annotating"
check "opened one of its own" "$(grep -c -- --session-id <<<"$argv")" "1"
check "with nothing to resume" "$(grep -c -- --resume <<<"$argv")" "0"

echo "an annotation's own earlier conversation is not resumed without a note"
run "" "last-nights-run"
check "opened one of its own" "$(grep -c -- --session-id <<<"$argv")" "1"
check "with nothing to resume" "$(grep -c -- --resume <<<"$argv")" "0"

echo "unless the CLI has dropped that conversation, and then it starts fresh"
run "" "tonights-solve solve" ""
check "opened one of its own" "$(grep -c -- --session-id <<<"$argv")" "1"
check "with nothing to resume" "$(grep -c -- --resume <<<"$argv")" "0"
check "on the annotation's own system prompt" "$(system 1)" "tools/annotate_prompt.md"

echo "with no session id to be had, the annotation starts fresh rather than resuming nothing"
SESSION_ID_BROKEN=1 run ""
check "the run still happened" "$calls" "1"
check "and succeeded" "${ok:-no}" "1"
check "resuming no conversation, least of all an empty one" \
  "$(grep -c -- --resume <<<"$argv")" "0"
check "and naming none either" "$(grep -c -- --session-id <<<"$argv")" "0"

# --- the solve side: what it leaves behind for the annotation to find ---
echo "a solve names its conversation, and that is the one the annotation resumes"
CALLS=$(mktemp -d); export CALLS MODE=""
export CLAUDE_CONFIG_DIR="$stub/config"
transcripts ""
. tools/claude_session.sh
rm -f "$sidfile"
worker_solve test-1 "$stub/fill" "$stub/solve.log" "$sidfile" 2>/dev/null
argv=$(cat "$CALLS/argv")
check "the solve call opened a named conversation" "$(grep -c -- --session-id <<<"$argv")" "1"
check "and wrote it down as a solve" "$(cat "$sidfile")" "$(opened 1) solve"
check "on the solve's system prompt" "$(system 1)" "tools/solve_prompt.md"
check "with no web to read the answers off" "$(grep -c 'WebSearch\|WebFetch' <<<"$argv")" "0"
solved="$(opened 1)"
rm -rf "$CALLS"
run "" "$(cat "$sidfile")"
check "the annotation that follows resumed it" "$(resumed 1)" "$solved"

echo "a session id the generator could not make is never passed as an empty one"
CALLS=$(mktemp -d); export CALLS
session_id() { return 1; }
worker_solve test-3 "$stub/fill" "$stub/solve.log" "$sidfile" 2>/dev/null
argv=$(cat "$CALLS/argv")
check "the solve ran with no --session-id rather than a blank one" \
  "$(grep -c -- --session-id <<<"$argv")" "0"
check "and left the annotation nothing to resume" "$([ -e "$sidfile" ] && echo there || echo none)" "none"
rm -rf "$CALLS"

[ "$fails" = 0 ] && echo "annotate retry: all checks passed" || echo "annotate retry: $fails FAILED"
exit $((fails > 0))
