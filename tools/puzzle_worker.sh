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
# The caller sets WORKER_MODEL, WORKER_EFFORT, WORKER_JOB (its name in alerts)
# and WORKER_WRAP (a command prefix such as "nice -n 19" or "timeout 90m", or
# empty), has CLAUDE_HEADLESS and alert() defined and tools/claude_session.sh
# sourced, and runs from the repo root. It may define on_fix_run, called
# with 1 and 0 around a validation-fix run.
#
# What stays the caller's is only scheduling: which ids, when, how many at
# once, the usage gates, and what to do with an id after each step's verdict.
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
# tools/apply_solution.py passes it, and commit and push it; the verdict goes
# to $4. 0 when the fill went in. Otherwise nothing is written, the
# solve ledger (tools/failed_inputs.py) records the rejection so the puzzle is
# not tried again on the same inputs, and the return is 1 — or 2 when there is
# nothing more to alert about: the ledger refused the entry as transient (a
# lockout, the network), or the commit was refused and has alerted already.
worker_apply() {   # id fill log verdict
  local id="$1" fill="$2" log="$3" verdict="$4" judged="" said="$3"
  if [ -s "$fill" ]; then
    # --no-reindex: the index is the caller's to rebuild when its run ends.
    if python3 tools/apply_solution.py "$id" --fill "$fill" --model "$WORKER_MODEL" --no-reindex >"$verdict" 2>&1; then
      # The solver's own account outlives the run, for the miss diagnosis to
      # read when the paper's key grades it.
      python3 tools/solve_misses.py keep-log "$id" "$log"
      worker_commit_solve "$id" && return 0
      echo "its commit was refused" >>"$verdict"
      return 2
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
#   $4 the task, worded for a fresh run
#   $5 a note to resume with instead (a retry after a cut-off), or empty
# Web lookup belongs to the annotation and to nothing else: a clue nobody can
# parse ships with no teaching ladder, so a solvers' blog is worth a fetch as a
# last resort (tools/annotate_check.py discloses it only once every clue but
# the last few is done, never up front).
# With a note, a live conversation is resumed with it. Without one, a live cold
# solve is resumed with the task behind a handover; anything else starts fresh.
# Returns the CLI's exit status (124 when a timeout WORKER_WRAP fired).
worker_annotate() {   # id log sidfile task [note]
  local id="$1" log="$2" sidfile="$3" prompt="$4" note="${5:-}"
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
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *),WebSearch,WebFetch" \
    --max-turns 80 >"$log" 2>&1
}

# --- after the model: validate, commit and push one puzzle ---------------------
# Both schedulers publish each puzzle as it is finished, by its own commit,
# pushed straight to origin/master by tools/push_puzzle_commit.sh without
# touching the tree, so a puzzle reaches the site without waiting for the rest
# of the run. The caller's end-of-run sync rebases the tree, which drops those
# commits as already upstream. WORKER_JOB names the caller in alerts.

# One puzzle's file as a git pathspec: puzzles/<series>/<year>/<id>.json in
# whichever year folder, so a write that moved it to another year is staged or
# undone as both halves of the rename.
puzzle_spec() { printf 'puzzles/*/*/%s.json' "$1"; }
# A puzzle held as its clues alone, as a git pathspec (tools/clues_only.py).
clues_spec() { printf 'clues_only/*/%s.json' "$1"; }
# The burn's runs share one index. Unlocked, one run's `git add` dies on
# index.lock while a sibling commits, and a commit takes whatever its siblings
# have staged. So each stages, commits and names its commit under this lock,
# and pushes that commit by name rather than HEAD.
index_lock() { exec 9>"$(git rev-parse --git-path ct-index.lock)"; flock 9; }
index_unlock() { flock -u 9; exec 9>&-; }
# Undo a run's edits to one puzzle, including a copy written to a new folder,
# and its rows of the source-correction tables (tools/data/source_*_wrong.json,
# fetch_puzzle.py): back as HEAD has them, then any SOURCE_CLUE_WRONG row left
# for a clue the reverted file does not show.
discard_puzzle() {
  git checkout -- "$(puzzle_spec "$1")" 2>/dev/null
  git clean -qf -- "$(puzzle_spec "$1")"
  { python3 tools/own_rows.py revert "$1" && python3 tools/discard_clue_rows.py "$1"; } ||
    alert "$WORKER_JOB could not put back $1's rows of tools/fetch_puzzle.py after discarding it; the sweep at the end of the run may carry rows its file does not show."
}
# Stage one puzzle for its commit: its file, and its rows of fetch_puzzle.py
# with no sibling's (tools/own_rows.py). On failure nothing is left staged, so
# the next puzzle's commit cannot carry this one.
stage_puzzle() {
  git add -A -- "$(puzzle_spec "$1")" && python3 tools/own_rows.py stage "$1" && return 0
  # shellcheck disable=SC2046  # one path per line, none with a space
  git reset -q -- "$(puzzle_spec "$1")" $(python3 tools/own_rows.py paths)
  return 1
}

# Commit what is staged as "$1" under the index lock and push it. $2.. are the
# pathspecs to unstage if the commit is refused. 0 when committed.
worker_commit() {   # subject paths...
  local subject="$1" out sha
  shift
  if ! out=$(git commit -q -m "$(printf '%s\n\n%s' "$subject" "$(python3 tools/provenance.py trailer)")" 2>&1); then
    # push_puzzle_commit.sh would find HEAD already on origin and exit 0, so a
    # refused commit has to stop here or the log says "committed".
    git reset -q -- "$@"
    index_unlock
    alert "$WORKER_JOB could not commit $subject, so it does not reach the site until this is fixed: $(printf '%s' "$out" | tail -5)"
    return 1
  fi
  sha=$(git rev-parse HEAD)
  index_unlock
  tools/push_puzzle_commit.sh "$sha" ||
    alert "$WORKER_JOB committed $subject but could not push it — the site will not show it until the run's closing sync pushes it."
  return 0
}

# A cold solve that worker_apply wrote: commit and push it ahead of its
# annotation. A puzzle held as its clues alone is promoted by that apply, which
# files the grid it derives and deletes the clues-only file: both go in.
worker_commit_solve() {   # id
  local id="$1" out
  local -a spec=("$(puzzle_spec "$id")")
  [ -n "$(git ls-files -- "$(clues_spec "$id")")" ] && spec+=("$(clues_spec "$id")")
  index_lock
  if ! out=$(git add -A -- "${spec[@]}" 2>&1); then
    git reset -q -- "${spec[@]}"
    index_unlock
    alert "$WORKER_JOB could not stage its solve of $id, so it is not annotated either: $(printf '%s' "$out" | tail -5)"
    discard_puzzle "$id"
    [ "${#spec[@]}" -gt 1 ] && git checkout -- "${spec[1]}"
    return 1
  fi
  worker_commit "Solve $id" "${spec[@]}" && return 0
  discard_puzzle "$id"
  [ "${#spec[@]}" -gt 1 ] && git checkout -- "${spec[1]}"
  return 1
}

# Blank the model answers ($2...) an annotation found no parse for, and commit
# and push that, so the puzzle is solved again. Non-zero, with the file put
# back, when any step fails; the puzzle is then parked like any other.
worker_reopen() {   # id entry...
  local id="$1" out
  shift
  if ! out=$(python3 tools/reopen_answers.py "$id" "$@" 2>&1); then
    alert "$WORKER_JOB could not reopen $id's unparsed model answers ($*), so it is parked instead: $(printf '%s' "$out" | tail -3)"
    discard_puzzle "$id"
    return 1
  fi
  index_lock
  if ! out=$(git add -A -- "$(puzzle_spec "$id")" 2>&1); then
    git reset -q -- "$(puzzle_spec "$id")"
    index_unlock
    alert "$WORKER_JOB could not stage reopening $id ($*), so it is parked instead: $(printf '%s' "$out" | tail -5)"
    discard_puzzle "$id"
    return 1
  fi
  worker_commit "Reopen $id $*"$'\n\n'"No parse was found for these model answers, so they go back to be solved again, once." \
    "$(puzzle_spec "$id")" || { discard_puzzle "$id"; return 1; }
  echo "  [$id] $out; to be solved again"
}

# A run that failed. One cut off by a lockout usually leaves real work behind:
# some clues annotated, the rest untouched, and that file still validates.
# Throwing it away means paying for those clues again, so it is kept, and a
# note for a retry that resumes the same conversation is written to $3. A
# half-written one — the run died mid-edit — is worth nothing: it is put back,
# and its conversation (sid file $4) forgotten, since it describes edits no
# longer on disk. 0 when kept.
worker_failed() {   # id what notefile sidfile
  local id="$1" what="$2" seen
  # What the retry is told to look at: the annotate run's copy, never the
  # puzzle itself, which names the blog.
  seen=$(python3 tools/puzzle_paths.py "$id")
  [ "$what" = Annotate ] && seen="tools/_puzzle_$id.json"
  if [ -n "$(git status --porcelain -- "$(puzzle_spec "$id")")" ] &&
     python3 tools/validate_annotations.py "$id" >/dev/null 2>&1; then
    echo "  [$id] run failed — keeping what it finished, the file still validates"
    printf '%s\n' "You were cut off by a usage limit. The limit has since cleared and your edits to $seen are exactly as you left them. Pick up where you stopped, finish the task you were given, and run python3 tools/annotate_check.py $id until it reports clean. Do not commit." >"$3"
    return 0
  fi
  echo "  [$id] run failed — discarding its changes"
  discard_puzzle "$id"
  rm -f "$4"
  return 1
}

# Validate, commit and push the puzzle a finished run ($3, $4: its sid file
# and log) left; $2 is the commit's verb ("Annotate", or a field
# backfill's). Returns 0 when it was committed or there was nothing to commit,
# 2 when its unparsed model answers were reopened to be solved again, 1 when
# it was discarded.
#
# A validation failure goes back to the conversation that wrote it once before
# anything is thrown away: a puzzle is twenty-odd clues of solving and the
# failure is usually one of them, and a fresh run would buy all of it again.
# A second failure means the run cannot see what is wrong, and repeating that
# is the waste this avoids. Only this puzzle is validated: a whole-tree run
# would fail for a sibling still mid-write.
worker_finish() {   # id what sidfile log
  local id="$1" what="$2" sidfile="$3" log="$4" vlog file reopen loss
  vlog="$(mktemp "${TMPDIR:-/tmp}/cryptic-validate.XXXXXX")"
  if ! python3 tools/validate_annotations.py "$id" >"$vlog" 2>&1; then
    file=$(python3 tools/puzzle_paths.py "$id")
    echo "  [$id] did not validate — handing the errors back rather than discarding the puzzle"
    local fix
    fix=$(printf '%s\n\n%s\n\n%s\n' "$file does not validate:" "$(grep -E '^  ERROR' "$vlog")" \
      "Fix those clues in $file and nothing else, following tools/annotate_prompt.md, then run python3 tools/annotate_check.py $id until it reports clean. Do not commit.")
    # Even a fix run the limit cuts off may have landed its edit, so the second
    # validation runs either way and decides on what is on disk.
    declare -F on_fix_run >/dev/null && on_fix_run 1
    worker_annotate "$id" "$log" "$sidfile" "$fix" "$fix" || true
    declare -F on_fix_run >/dev/null && on_fix_run 0
  fi
  if ! python3 tools/validate_annotations.py "$id" >"$vlog" 2>&1; then
    tail -5 "$vlog"
    # A model's answer the run could not parse may be the wrong word, and a
    # failure record would hold it until its inputs change, which is never. So
    # those answers are blanked and the puzzle solved again instead, once per
    # entry (tools/reopen_answers.py); read before the discard, off the run's file.
    reopen=$(python3 tools/reopen_answers.py "$id" --which) || reopen=""
    if [ -n "$reopen" ]; then
      discard_puzzle "$id"
      # shellcheck disable=SC2086 # $reopen is a list of entry ids
      worker_reopen "$id" $reopen && { rm -f "$vlog"; return 2; }
    fi
    # Parked: the work is thrown away and the puzzle stays unannotated until
    # its inputs change, which only a person mending the clue or answer does,
    # so this is said out loud. Quoting the failure line verbatim marks it
    # claimed for alert.sh.
    alert "$what $id was discarded — it did not validate, so that puzzle stays unannotated:"$'\n'"VALIDATION FAILED after $what $id — discarding that puzzle's changes"$'\n'"\`\`\`"$'\n'"$(grep -E '^  ERROR' "$vlog" | head -5)"$'\n'"\`\`\`"
    # Recorded against the puzzle's inputs: this run finished and was rejected,
    # the one failure that says something about the grid. A misread clue on an
    # OCR'd puzzle is the scan's to read again instead (annotate_check.py
    # --reread; once per reading of its clues).
    python3 tools/annotate_check.py --reread "$id" ||
      python3 tools/failed_inputs.py record annotate "$id" --judged \
        --reason "$(grep -E '^  ERROR' "$vlog" | head -1 | cut -c1-200)" || true
    discard_puzzle "$id"
    rm -f "$vlog"
    return 1
  fi
  rm -f "$vlog"
  # Solved-but-short is not a failure: the nulled clues ship as "answers only".
  # Say so, once, per puzzle.
  loss=$(python3 tools/check_annotation_loss.py "$id" 2>&1) ||
    alert "$WORKER_JOB left clues blank — $loss. They ship with no teaching ladder."
  echo "$loss"
  # A printedClue this run filed on an OCR'd puzzle asks its scan to be read
  # again, so the OCR learns what the annotator mended.
  python3 tools/annotate_check.py --reread "$id" || true
  if [ -z "$(git status --porcelain -- "$(puzzle_spec "$id")")" ]; then
    echo "$what $id produced no change"
    # A clean exit is not evidence of hints: a run can finish its turns having
    # written nothing, and the validator is happy with a file with nothing in
    # it to be wrong. So it is recorded like any other lost run.
    [ "$what" = Annotate ] &&
      python3 tools/failed_inputs.py record annotate "$id" --judged \
        --reason "the run exited cleanly but wrote no annotation"
    return 0
  fi
  # -A, so a file that changed year folders goes in as a rename rather than as
  # a new copy beside the old one. Its rows of fetch_puzzle.py go with it, and
  # only its own: a corrected clue is valid only beside its SOURCE_CLUE_WRONG
  # row, and siblings still in flight file theirs into the same file.
  index_lock
  local out
  if ! out=$(stage_puzzle "$id" 2>&1); then
    index_unlock
    alert "$WORKER_JOB could not stage $id's rows of tools/fetch_puzzle.py, so $what $id is not committed: $(printf '%s' "$out" | tail -5)"
    return 1
  fi
  # shellcheck disable=SC2046  # one path per line, none with a space
  worker_commit "$what $id" "$(puzzle_spec "$id")" $(python3 tools/own_rows.py paths) || return 1
  python3 tools/failed_inputs.py clear annotate "$id" >/dev/null
  echo "committed $what $id"
  return 0
}
