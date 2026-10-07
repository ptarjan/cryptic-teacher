# shellcheck shell=bash
# One puzzle's model work: solve it cold when it has no key, annotate it in that
# same conversation, and record a solve the applier refused. Sourced by the
# nightly (tools/daily_update.sh) and the burn (tools/prereset_backfill.sh),
# which differ only in which ids they pick, when, how many at once and how they
# pace themselves. This is the only file that runs a model on
# tools/solve_prompt.md or tools/annotate_prompt.md, and
# tools/test_puzzle_worker.sh holds it to that.
#
# A cold solve runs only as the first half of annotating the same puzzle: the
# caller asks for one immediately before the annotation it feeds, never as a
# pick of its own. Working an answer out and explaining how it was worked out
# are the same reasoning, so the annotation resumes the solve's conversation
# rather than buying that reasoning twice.
#
# The caller sets WORKER_MODEL, WORKER_EFFORT and WORKER_WRAP (a command prefix
# such as "nice -n 19" or "timeout 90m", or empty), has CLAUDE_HEADLESS defined
# and tools/claude_session.sh sourced, and runs from the repo root.
#
# A conversation is named by a sid file: "<session id>" for an annotation's own,
# "<session id> solve" for a cold solve's not yet handed over, and
# "<session id> annotating" once it has been. A conversation that began as a
# solve keeps tools/solve_prompt.md as its system prompt on every later turn,
# because a resume must send the one it began with or its cached prefix stops
# matching; and it is handed over once, so a later fresh task on the same id
# does not land in it.

worker_sid() { local sid _; [ -s "$1" ] && read -r sid _ <"$1" && printf '%s\n' "$sid"; }

# Solve $1 cold, writing its fill to $2 and the transcript to $3, in a new
# conversation named in sid file $4. Returns the CLI's exit status; whether the
# fill is any good is worker_apply's call.
worker_solve() {   # id fill log sidfile
  local id="$1" fill="$2" log="$3" sidfile="$4" sid sess=()
  rm -f "$fill" "$sidfile"
  if sid=$(session_id); then
    sess=(--session-id "$sid")
    echo "$sid solve" >"$sidfile"
  fi
  # No web: the paper's answers are unpublished but the blogs are not, and a
  # solve that reads the answers measures nothing.
  # shellcheck disable=SC2086 # $WORKER_WRAP is a command and its arguments, or nothing
  $WORKER_WRAP claude -p "Solve the cryptic crossword in $(python3 tools/puzzle_paths.py "$id") in this repo. Its answers have not all been published, so there is no key: follow tools/solve_prompt.md exactly (it is your system prompt's appendix; do not open the file), write your fill to $fill, and iterate against 'python3 tools/apply_solution.py $id --fill $fill --check-only' until every crossing agrees. Do not write to puzzles/ — the calling script applies the fill." \
    "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
    --append-system-prompt-file tools/solve_prompt.md \
    --exclude-dynamic-system-prompt-sections \
    --model "$WORKER_MODEL" \
    --effort "$WORKER_EFFORT" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
    --max-turns 120 >"$log" 2>&1
}

# Write the fill worker_solve left at $2 into the puzzle, if
# tools/apply_solution.py passes it; the verdict goes to $4. Extra arguments go
# to the applier. 0 when the fill went in. Otherwise nothing is written, the
# solve ledger (tools/failed_inputs.py) records the rejection so the puzzle is
# not tried again on the same inputs, and the return is 1 — or 2 when the
# ledger refused the entry as transient (a lockout, the network), which is
# nothing to alert about. A rejected solve's sid file goes: nothing may resume it.
worker_apply() {   # id fill log verdict [applier args...]
  local id="$1" fill="$2" log="$3" verdict="$4" judged="" said="$3"
  if [ -s "$fill" ]; then
    if python3 tools/apply_solution.py "$id" --fill "$fill" --model "$WORKER_MODEL" "${@:5}" >"$verdict" 2>&1; then
      # The solver's own account outlives the run, for the miss diagnosis to
      # read when the paper's key grades it.
      python3 tools/solve_misses.py keep-log "$id" "$log"
      return 0
    fi
    judged=--judged said="$verdict"
  else
    echo "the solver finished without writing a fill to $fill at all" >"$verdict"
  fi
  # A fill the applier refused is its verdict on the puzzle. No fill at all
  # means the CLI stopped, and its last line says whether that was transient.
  # shellcheck disable=SC2086 # $judged is one flag or nothing
  python3 tools/failed_inputs.py record solve "$id" $judged \
    --reason "$(grep -v '^[[:space:]]*$' "$said" | tail -1 | cut -c1-200)" || return 2
  return 1
}

# Annotate $1, transcript to $2, in the conversation sid file $3 names.
#   $4 the allowed tools  $5 max turns  $6 the task, worded for a fresh run
#   $7 a note to resume with instead (a retry after a cut-off), or empty
# With a note, a live conversation is resumed with it. Without one, a live cold
# solve is resumed with the task behind a handover; anything else starts fresh.
# Returns the CLI's exit status (124 when a timeout WORKER_WRAP fired).
worker_annotate() {   # id log sidfile tools turns task [note]
  local id="$1" log="$2" sidfile="$3" tools="$4" turns="$5" prompt="$6" note="${7:-}"
  local sid="" kind="" sess=() sys=tools/annotate_prompt.md
  [ -s "$sidfile" ] && read -r sid kind <"$sidfile"
  if session_exists "$sid" && { [ -n "$note" ] || [ "$kind" = solve ]; }; then
    sess=(--resume "$sid")
    if [ -n "$note" ]; then
      prompt="$note"
    else
      echo "$sid annotating" >"$sidfile"
      echo "  $id was solved cold just now — annotating in that same conversation rather than from a cold start"
      # The transcript ends before apply_solution.py wrote the fill, so the
      # run is sent back to the file rather than trusted to memory.
      prompt="You solved this crossword earlier in this conversation, and your fill has since been written into the puzzle file. Read the file as it now stands rather than working from memory, then annotate it from the wordplay you used to derive each answer. tools/annotate_prompt.md is not in your system prompt this time: read it first and follow it exactly wherever the task below points at it. The task: $prompt"
    fi
    case "$kind" in solve|annotating) sys=tools/solve_prompt.md ;; esac
  else
    rm -f "$sidfile"
    if sid=$(session_id); then
      sess=(--session-id "$sid")
      echo "$sid" >"$sidfile"
    fi
  fi
  # shellcheck disable=SC2086 # $WORKER_WRAP is a command and its arguments, or nothing
  $WORKER_WRAP claude -p "$prompt" "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
    --append-system-prompt-file "$sys" \
    --exclude-dynamic-system-prompt-sections \
    --model "$WORKER_MODEL" \
    --effort "$WORKER_EFFORT" \
    --allowedTools "$tools" \
    --max-turns "$turns" >"$log" 2>&1
}
