# shellcheck shell=bash
# One puzzle's model work: annotate it, solving it cold first in that same turn
# when it has no key, and check, commit and push what the run left. Sourced by
# the nightly (tools/daily_update.sh) and the burn (tools/prereset_backfill.sh),
# which differ only in which ids they pick, when, how many at once and how they
# pace themselves. This is the only file that runs a model on
# tools/solve_prompt.md or tools/annotate_prompt.md, and
# tools/test_puzzle_worker.sh holds it to that.
#
# A cold solve runs only inside the turn that annotates the same puzzle, never
# as a pick of its own: working an answer out and explaining how it was worked
# out are the same reasoning, so one turn does both. The run applies its own
# fill to have a grid to annotate; worker_apply then checks that fill again
# from the committed puzzle, and nothing built on a fill it refuses ships.
#
# The caller sets WORKER_MODEL, WORKER_EFFORT, WORKER_JOB (its name in alerts)
# and WORKER_WRAP (a command prefix such as "nice -n 19" or "timeout 90m", or
# empty), has CLAUDE_HEADLESS and alert() defined and tools/claude_session.sh
# sourced, and runs from the repo root. It may define on_fix_run, called
# with 1 and 0 around a validation-fix run.
#
# A bag is one conversation that annotates the missing clues of several tail
# puzzles at once (tools/prereset_plan.py bag_of): the caller names its puzzles,
# one per line, in <job dir>/<leader>.bag beside the leader's sid file. The
# leader's id names the conversation, its sid file, its log and its note; every
# per-puzzle step below (set aside, put back, failed, finish) runs once per
# puzzle still listed there, each puzzle validated on its own and all that
# validated committed together as one "Annotate N puzzles: ..." commit
# (worker_commit_batch; 10-17, Paul: origin was flooded with a commit per
# puzzle), and a puzzle that fails costs only itself: it is left out of the
# batch. worker_bag_ids lists them.
#
# What stays the caller's is only scheduling: which ids, when, how many at
# once, the usage gates, and what to do with an id after each step's verdict.
#
# A conversation is named by a sid file: "<session id>", or "<session id> solve"
# for one that began with a cold solve, which has no web on any of its turns.
# Every turn sends tools/annotate_prompt.md as its system prompt, so a resume's
# cached prefix always matches.

# The bag's batch: the ids _worker_finish queued instead of committing (while
# WORKER_BATCH_ON is set), and what each needs settled once committed.
WORKER_BATCH_ON=""
WORKER_BATCH_IDS=()
declare -gA WORKER_BATCH_POST=()

worker_sid() { local sid _; [ -s "$1" ] && read -r sid _ <"$1" && printf '%s\n' "$sid"; }
worker_kind() { local _ kind=""; [ -s "$1" ] && read -r _ kind _ <"$1"; printf '%s\n' "$kind"; }

# --- interrupted runs ----------------------------------------------------------
# A run can be stopped from outside (a restart, its unit's time limit) with its
# conversation on disk and its edits in a tree the next start resets. So every
# conversation's sid file lives beside the checkout all trees share,
# .ct-runs/<job>/<id>.sid, with <id>.tree (the tree it runs in) and <id>.fill
# (a cold solve's fill). Not in the git dir: the run writes its fill there
# itself, and Claude Code refuses any write under .git as a sensitive file. It is forgotten when the puzzle's fate is settled
# (worker_finish, a rejected solve, a dropped run); one still there when its id
# is next launched is an interrupted run, and that launch resumes it
# (worker_put_back). A record a day old is dropped instead: its tree has moved on.
worker_runs_root() {   # [tree] -> where every job's records live
  local g
  g="$(git ${1:+-C "$1"} rev-parse --path-format=absolute --git-common-dir)" &&
    printf '%s\n' "$(dirname "$g")/.ct-runs"
}
worker_runs() {   # job -> its record directory, made if missing
  local d
  d="$(worker_runs_root)/$1" && mkdir -p "$d" && printf '%s\n' "$d"
}
worker_forget() {   # sidfile
  local rec="${1%.sid}"
  rm -rf "$rec.sid" "$rec.tree" "$rec.fill" "$rec.aside" "$rec.mended" "$rec.bag"
}
# The puzzles conversation $1 (a sid file) is working: the ones its bag still
# lists, or just its own id when it is not a bag.
worker_bag_ids() {   # sidfile
  local rec="${1%.sid}"
  if [ -s "$rec.bag" ]; then cat "$rec.bag"; else basename "$rec"; fi
}
# Take puzzle $2 off conversation $1's bag once its fate is settled; the bag file
# goes with its last puzzle.
worker_bag_drop() {   # sidfile id
  local bag="${1%.sid}.bag" rest
  [ -s "$bag" ] || return 0
  rest=$(grep -vxF -- "$2" "$bag")
  if [ -n "$rest" ]; then printf '%s\n' "$rest" >"$bag"; else rm -f "$bag"; fi
}
worker_stale() { [ -n "$(find "$1" -mmin +1440 2>/dev/null)" ]; }

# Copy what an interrupted run left in tree $1 beside its record (sid file $2)
# before anything resets that tree: its puzzle's files as the tree has them
# (edited, new, or a promoted clues-only file deleted), its annotation files,
# its tables of source corrections, and the commit those are edits of.
# Read-only on the tree, and once per record.
worker_set_aside() {   # tree sidfile
  local tree="$1" rec="${2%.sid}" id p
  local -a specs=() names=()
  [ -e "$rec.aside" ] && return 0
  for id in $(worker_bag_ids "$2"); do
    specs+=("$(puzzle_spec "$id")" "$(clues_spec "$id")")
    names+=("tools/_ann_$id.json" "tools/_puzzle_$id.json")
  done
  if ! { mkdir -p "$rec.aside/files" "$rec.aside/rows" &&
         git -C "$tree" rev-parse HEAD >"$rec.aside/base"; }; then
    rm -rf "$rec.aside"
    return 1
  fi
  while IFS= read -r p; do
    [ -f "$tree/$p" ] || continue
    mkdir -p "$rec.aside/files/$(dirname "$p")" && cp -p "$tree/$p" "$rec.aside/files/$p"
  done < <(git -C "$tree" ls-files -m -o --exclude-standard -- "${specs[@]}"
           cd "$tree" && ls "${names[@]}" 2>/dev/null)
  git -C "$tree" ls-files -d -- "${specs[@]}" >"$rec.aside/deleted"
  while IFS= read -r p; do
    git -C "$tree" diff --quiet HEAD -- "$p" && continue
    mkdir -p "$rec.aside/rows/$(dirname "$p")" && cp -p "$tree/$p" "$rec.aside/rows/$p"
  done < <(cd "$tree" && python3 tools/own_rows.py paths)
}

# Every record of any job that ran in tree $1, set aside: called before the
# tree is reset (tools/nightly_worktree.sh). Stale records are dropped here.
worker_set_aside_tree() {   # tree
  local runs sid
  runs="$(worker_runs_root "$1")"
  [ -d "$runs" ] || return 0
  for sid in "$runs"/*/*.sid; do
    [ -f "$sid" ] || continue
    if worker_stale "$sid"; then worker_forget "$sid"; continue; fi
    [ "$(cat "${sid%.sid}.tree" 2>/dev/null)" = "$1" ] || continue
    worker_set_aside "$1" "$sid" ||
      echo "could not set aside $(basename "${sid%.sid}")'s interrupted run in $1" >&2
  done
  # What a forgotten record left (an aside, a fill) goes a day after it.
  find "$runs" -mindepth 2 -maxdepth 2 ! -name '*.sid' -mmin +2880 -exec rm -rf {} + 2>/dev/null
  return 0
}

# Before id $1 is launched: when its record (sid file $4) is still there, the
# last run on it was interrupted, and this launch resumes that conversation.
# Its set-aside files come back into this tree only when HEAD holds the
# puzzle's files as the commit they are edits of did: master has not touched
# the puzzle since. Then worker_failed's rule decides what is kept. Writes the
# note to resume with to $3; 0 when there is one, 1 when the id starts fresh.
worker_put_back() {   # id what notefile sidfile
  local id="$1" what="$2" notefile="$3" sidfile="$4" rec="${4%.sid}" sid tree p moved="" m
  [ -s "$sidfile" ] || return 1
  sid=$(worker_sid "$sidfile")
  if worker_stale "$sidfile" || ! session_exists "$sid"; then
    worker_forget "$sidfile"
    return 1
  fi
  tree=$(cat "$rec.tree" 2>/dev/null)
  [ -n "$tree" ] && [ "$tree" != "$(pwd -P)" ] && [ -d "$tree" ] && worker_set_aside "$tree" "$sidfile"
  if [ -d "$rec.aside" ]; then
    local -a specs=()
    for m in $(worker_bag_ids "$sidfile"); do specs+=("$(puzzle_spec "$m")" "$(clues_spec "$m")"); done
    if git diff --quiet "$(cat "$rec.aside/base")" HEAD -- "${specs[@]}" 2>/dev/null; then
      for m in $(worker_bag_ids "$sidfile"); do restore_puzzle "$m"; done
      while IFS= read -r p; do
        mkdir -p "$(dirname "$p")" && cp -p "$rec.aside/files/$p" "$p"
      done < <(cd "$rec.aside/files" && find . -type f | sed 's|^\./||')
      while IFS= read -r p; do rm -f "$p"; done <"$rec.aside/deleted"
      for m in $(worker_bag_ids "$sidfile"); do python3 tools/own_rows.py graft "$m" "$rec.aside/rows"; done
    else
      moved=1
    fi
    rm -rf "$rec.aside"
  fi
  echo "  [$id] resuming its interrupted conversation"
  worker_failed "$id" "$what" "$notefile" "$sidfile" \
    "were stopped from outside (the job restarted or hit its time limit)" "$moved"
  return 0
}

# Before a cold solve of id $1 is paid for: a clues-only puzzle whose clue list
# no grid can hold (tools/clues_only.py implausible: an OCR'd light lost or
# doubled) can only end "no single grid holds these answers", after the whole
# solve (10-08..12: grid-search failures were 4.5% of the burn's spend). So it
# is recorded against its inputs instead of run. 0 when it was recorded and
# must not be launched.
worker_implausible() {   # id
  local why
  why=$(python3 tools/clues_only.py implausible "$1") && return 1
  [ -n "$why" ] || return 1
  echo "  [$1] not solving: $why"
  python3 tools/failed_inputs.py record solve "$1" --judged --reason "$why" >/dev/null || true
  return 0
}

# Annotate $1, transcript to $2, in the conversation sid file $3 names.
#   $4 the task, worded for a fresh run
#   $5 a note to resume with instead (a retry after a cut-off), or empty
#   $6 for a puzzle with no key: the path the run writes its cold solve's fill
#      to, which worker_apply checks once the run is over
# With a note, a live conversation is resumed with it; anything else starts
# fresh. Web lookup belongs to the annotation of a keyed puzzle and nothing
# else: a clue nobody can parse ships with no teaching ladder, so a solvers'
# blog is worth a fetch as a last resort (tools/annotate_check.py discloses it
# only once every clue but the last few is done, never up front), but a solve
# that reads the answers measures nothing.
# Returns the CLI's exit status (124 when a timeout WORKER_WRAP fired).
worker_annotate() {   # id log sidfile task [note] [fill]
  local id="$1" log="$2" sidfile="$3" prompt="$4" note="${5:-}" fill="${6:-}"
  local sid="" kind="" sess=() tools="Read,Write,Edit,Bash(python3 *),Bash(node *)" bag m
  [ -s "$sidfile" ] && read -r sid kind _ <"$sidfile"
  if [ -n "$note" ] && session_here "$sid"; then
    sess=(--resume "$sid")
    prompt="$note"
    touch "$sidfile"
  else
    bag=$id
    [ -s "${sidfile%.sid}.bag" ] && bag=$(cat "${sidfile%.sid}.bag")
    worker_forget "$sidfile"
    [ "$bag" = "$id" ] || printf '%s\n' "$bag" >"${sidfile%.sid}.bag"
    kind=""
    # A fresh conversation has withdrawn nothing (worker_withdrawn).
    for m in $bag; do rm -f "tools/_withdrawn_$m.txt"; done
    if [ -n "$fill" ]; then
      kind=solve
      rm -f "$fill"
      prompt="Solve the cryptic crossword $id cold first: its answers have not all been published, so there is no key. Read tools/solve_prompt.md and follow it exactly, writing your fill to $fill; WebSearch and WebFetch are refused in this run, and the puzzle file the task names does not exist until the solve is applied: call neither, and do not Read it before then. It ends by handing you this task: $prompt"
    fi
    if sid=$(session_id); then
      sess=(--session-id "$sid")
      echo "$sid${kind:+ $kind}" >"$sidfile"
      pwd -P >"${sidfile%.sid}.tree"
    fi
  fi
  [ "$kind" = solve ] || tools="$tools,WebSearch,WebFetch"
  # --tools and --disable-slash-commands fix the cached prefix (system prompt,
  # tool definitions, skill and agent listings) to the same bytes for every
  # puzzle and both kinds of run, and drop the tools, skills and agents these
  # runs never use. --allowedTools, not --tools, decides what a run may call.
  # shellcheck disable=SC2086 # $WORKER_WRAP is a command and its arguments, or nothing
  # CT_TASK_PUZZLE: tools/puzzle_paths.py resolve_puzzle reads it, so a bare
  # number the run types that two papers share still means this puzzle.
  CT_TASK_PUZZLE="$id" $WORKER_WRAP claude -p "$prompt" "${sess[@]}" "${CLAUDE_HEADLESS[@]}" \
    --append-system-prompt-file tools/annotate_prompt.md \
    --exclude-dynamic-system-prompt-sections \
    --tools Read,Write,Edit,Bash,WebSearch,WebFetch \
    --disable-slash-commands \
    --model "$WORKER_MODEL" \
    --effort "$WORKER_EFFORT" \
    --allowedTools "$tools" \
    --max-turns "$([ "$kind" = solve ] && echo 200 || echo 80)" >"$log" 2>&1
}

# The one line that says why output $1 failed, for logs and the solve ledger.
# An applier verdict (tools/apply_solution.py: "REJECTED — N problem(s)" over
# an indented list) gives its FIRST problem and how many more: the list puts
# answers before definitions, so its last line read "no definition given" for
# a solve that had left a third of the grid unanswered (genius-41: 16 of 28,
# 10-13), and the burn's log blamed the definitions. Anything else gives its
# last non-blank line, as before.
worker_verdict_line() {   # file
  awk '
    /^REJECTED — [0-9]+ problem|^[^ ]+: REJECTED, held clues-only/ && !hdr { hdr = 1; if (match($0, /[0-9]+ problem/)) n = substr($0, RSTART, RLENGTH) + 0; next }
    hdr && /^  [^ ]/ { c++; if (first == "") { first = $0; sub(/^ +/, "", first) } }
    NF { last = $0 }
    END {
      if (first == "") { print last; exit }
      if (!n) n = c
      print first (n > 1 ? " (and " n - 1 " more)" : "")
    }' "$1"
}

# Check the cold solve a finished run (transcript $3) wrote to $2, from the
# puzzle as committed: its file, and a clues-only file the run's own apply
# promoted, go back to HEAD; tools/apply_solution.py writes the fill in only if
# it passes; and the annotations the run wrote (tools/_ann_<id>.json) are put
# back on top by tools/annotate_check.py. So what ships is a fill the applier
# accepted with the hints built on it. The verdict goes to $4; $5 is the run's
# sid file. 0 when the fill and its hints went in. Otherwise the puzzle, its
# rows and the run's annotation files are discarded, and the return is 2 when
# the hints did not land (alerted, and recorded against the puzzle's inputs
# when the validator refused them); for a refused fill the solve ledger
# (tools/failed_inputs.py) records the rejection so the puzzle is not tried
# again on the same inputs, and the return is 1 — or 2 when the ledger refused
# the entry as transient (a lockout, the network).
#
# With $6, a resume-note path, two refusals of the fill (worker_mendable) and
# hints that did not land on an accepted one (worker_mend_hints) are mended
# rather than thrown away, once per conversation: returns 3 with the note
# written and the conversation, its fill and its annotations kept, for the
# caller to resume it.
worker_apply() {   # id fill log verdict sidfile [notefile]
  local id="$1" fill="$2" log="$3" verdict="$4" sidfile="$5" notefile="${6:-}" judged="" said="$3" rc error why
  # A run that took its work back has neither its fill nor its hints applied.
  if why=$(worker_withdrawn "$id" "$log"); then
    worker_withdraw "$id" "$why"
    echo "withdrawn by the run — $why" >"$verdict"
    return 2
  fi
  restore_puzzle "$id"
  if [ -s "$fill" ]; then
    # --no-reindex: the index is the caller's to rebuild when its run ends.
    if python3 tools/apply_solution.py "$id" --fill "$fill" --model "$WORKER_MODEL" --no-reindex >"$verdict" 2>&1; then
      # The solver's own account outlives the run, for the miss diagnosis to
      # read when the paper's key grades it.
      python3 tools/solve_misses.py keep-log "$id" "$log"
      # The hints are the run's, so they land as its session's: that is where
      # apply_annotations reads their author. Their validation is
      # worker_finish's to act on; hints that did not land at all (2) leave
      # the fill without them, and the rows they filed without their clues.
      CLAUDE_CODE_SESSION_ID="$(worker_sid "$sidfile")" python3 tools/annotate_check.py "$id" >>"$verdict" 2>&1
      rc=$?
      [ "$rc" -ne 2 ] && return 0
      discard_puzzle "$id"
      if worker_mend_hints "$id" "$fill" "$verdict" "$sidfile" "$notefile"; then
        return 3
      fi
      rm -f "tools/_ann_$id.json" "tools/_puzzle_$id.json"
      # apply_annotations' own refusal first: the lines after it are the
      # validator's preview, which may not name what stopped the write.
      alert "$WORKER_JOB solved $id but could not put its hints back on the fill, so nothing it wrote ships:"$'\n'"\`\`\`"$'\n'"$( { grep '^apply_annotations' "$verdict" | head -3; grep -v '^[[:space:]]*$' "$verdict" | tail -4; } | cut -c1-200)"$'\n'"\`\`\`"
      # A validator error is a verdict on what the run wrote, so the puzzle is
      # not solved again until its inputs change. A refusal with none (no
      # session to land them as) is ours, and says nothing about the puzzle.
      error=$(grep -E '^  ERROR' "$verdict" | head -1 | cut -c1-200)
      [ -z "$error" ] ||
        python3 tools/failed_inputs.py record annotate "$id" --judged --reason "$error" || true
      return 2
    fi
    judged=--judged said="$verdict"
  else
    echo "the run finished without writing a fill to $fill at all" >"$verdict"
  fi
  if worker_mendable "$id" "$fill" "$verdict" "$sidfile" "$notefile"; then
    discard_puzzle "$id"
    return 3
  fi
  discard_puzzle "$id"
  rm -f "tools/_ann_$id.json" "tools/_puzzle_$id.json"
  # A fill the applier refused is its verdict on the puzzle. No fill at all
  # means the CLI stopped, and its last line says whether that was transient.
  # shellcheck disable=SC2086 # $judged is one flag or nothing
  python3 tools/failed_inputs.py record solve "$id" $judged \
    --reason "$(worker_verdict_line "$said" | cut -c1-200)" || return 2
  return 1
}

# Whether a refused cold solve (verdict $3) is worth resuming instead of
# discarding, and if so the note to resume it with, written to $5. Two
# refusals waste a whole solve over a few minutes' work (10-08..12):
#   - no fill at all (2.2% of the burn's spend): the run stopped without
#     writing one, so the next solve started from nothing;
#   - a fill refused only for definitions it left out (1.7%): every answer
#     placed, one field short.
# Once per conversation (the .mended mark beside its sid file), and only for a
# conversation that still exists to resume: a second refusal is recorded as
# before. 0 when the note was written.
worker_mendable() {   # id fill verdict sidfile notefile
  local id="$1" fill="$2" verdict="$3" sidfile="$4" notefile="$5" mark="${4%.sid}.mended" probs defs note
  [ -n "$notefile" ] && [ ! -e "$mark" ] || return 1
  declare -F session_exists >/dev/null && session_exists "$(worker_sid "$sidfile")" || return 1
  if [ ! -s "$fill" ]; then
    note="You stopped without writing your fill to $fill, so everything you worked out would be thrown away. Write it now with the Write tool: your best answer and definition for every entry, adding \"guess\": true to any entry you are unsure of. Then run python3 tools/apply_solution.py $id --fill $fill --check-only, fix what it reports, and carry on as tools/solve_prompt.md says. If the check still cannot pass, leave the fill written and stop. Do not commit."
  else
    probs=$(grep -E '^  [0-9]+-(across|down): ' "$verdict")
    defs=$(grep -E '^  [0-9]+-(across|down): no definition given$' <<<"$probs")
    [ -n "$defs" ] && [ "$defs" = "$probs" ] || return 1
    note="The check refused your fill in $fill only for definitions it leaves out:"$'\n'"$defs"$'\n'"Every answer is placed; add each named entry's definition, copied verbatim from its clue, and run python3 tools/apply_solution.py $id --fill $fill --check-only until it passes. Then carry on as tools/solve_prompt.md says: apply the fill, make the copy you annotate, finish the annotation, and run python3 tools/annotate_check.py $id until it reports clean. Do not commit."
  fi
  touch "$mark"
  printf '%s\n' "$note" >"$notefile"
  echo "  [$id] $(worker_verdict_line "$verdict" | cut -c1-120) — resuming its conversation once to mend it"
  return 0
}

# Whether hints that did not land on an accepted fill (annotate_check STOPPED,
# verdict $3) go back to their conversation instead of being thrown away with
# the fill: usually one clue's fault, and a fresh run buys the whole solve and
# every other hint again (nation-3447, 10-12). Once per conversation, sharing
# worker_mendable's mark. 0 when the note was written to $5.
worker_mend_hints() {   # id fill verdict sidfile notefile
  local id="$1" fill="$2" verdict="$3" sidfile="$4" notefile="$5" mark="${4%.sid}.mended"
  [ -n "$notefile" ] && [ ! -e "$mark" ] || return 1
  declare -F session_exists >/dev/null && session_exists "$(worker_sid "$sidfile")" || return 1
  touch "$mark"
  printf '%s\n%s\n\n%s\n' "Your fill passed the check, but your annotations did not land on it, so nothing has been written:" \
    "$(grep -v '^[[:space:]]*$' "$verdict" | grep -v '^annotate_check ' | tail -20 | cut -c1-400)" \
    "The puzzle file is back as committed. Apply your fill again with python3 tools/apply_solution.py $id --fill $fill --no-reindex, fix what is listed above in tools/_ann_$id.json (leave null only a clue you cannot parse), and run python3 tools/annotate_check.py $id until it reports clean. Do not commit." >"$notefile"
  echo "  [$id] its hints did not land on the fill — resuming its conversation once to mend them"
  return 0
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
# The series folder is the id's part before its last "-" (series.parse_id,
# puzzle_paths.series_folder), so it is spelled out: a `*` there matches
# each of the ~66k untracked puzzles/<id>/ shim folders too, and `ls-files -o`,
# `status` and `clean` then open every one, ~2 s of CPU a call against
# ~0.02 s (10-15). A bare-number id keeps the wildcard.
puzzle_spec() {
  case $1 in
    *-*) printf 'puzzles/%s/*/%s.json' "${1%-*}" "$1" ;;
    *) printf 'puzzles/*/*/%s.json' "$1" ;;
  esac
}
# A puzzle held as its clues alone, as a git pathspec (tools/clues_only.py).
clues_spec() { printf 'clues_only/*/%s.json' "$1"; }
# One puzzle's pathspecs into the array named $2: its file, and its clues-only
# file while git tracks one, which the apply that promotes it deletes.
puzzle_specs() {   # id array-name
  local -n _specs="$2"
  _specs=("$(puzzle_spec "$1")")
  [ -n "$(git ls-files -- "$(clues_spec "$1")")" ] && _specs+=("$(clues_spec "$1")")
  return 0
}
# Put one puzzle's file, and a clues-only file promoted from it, back as HEAD
# has them, including a copy written to a new folder.
restore_puzzle() {
  under_index_lock git checkout -- "$(puzzle_spec "$1")" 2>/dev/null
  git clean -qf -- "$(puzzle_spec "$1")"
  [ -n "$(git ls-files -- "$(clues_spec "$1")")" ] && under_index_lock git checkout -- "$(clues_spec "$1")"
  return 0
}
# The burn's runs share one index. Unlocked, one run's `git add` dies on
# index.lock while a sibling commits, and a commit takes whatever its siblings
# have staged. So each stages, commits and names its commit under this lock,
# and pushes that commit by name rather than HEAD. fd 8: fd 9 is the tree's
# lease (tools/nightly_worktree.sh), held for the whole run.
index_lock() { exec 8>"$(git rev-parse --git-path ct-index.lock)"; flock 8; }
index_unlock() { flock -u 8; exec 8>&-; }
# One git command that rewrites the index (a checkout, a reset --keep, which on
# this tree's index run for seconds) taken in turn with the runs' stage and
# commit. Unlocked, the sync's tree-wide checkout held index.lock long enough to
# fail genius-177's stage on all five tries (10-17 12:26, with the retries then
# sleeping 8s in all). For callers NOT holding ct-index.lock: it waits on a
# fresh fd, 7, and goes ahead after five minutes rather than deadlock.
under_index_lock() {
  local lock
  lock=$(git rev-parse --git-path ct-index.lock 2>/dev/null) || lock=""
  [ -n "$lock" ] || { "$@"; return; }   # no lock path (a stubbed git): just run it
  ( exec 7>"$lock" && flock -w 300 7; "$@" )   # not exec: "$@" may be a shell function (a test's git stub)
}
# Copy what a run wrote for puzzle $1 to $SALVAGE_ROOT/<id>/<UTC time>/ before
# a discard throws it away: tools/_ann_<id>.json, tools/_puzzle_<id>.json, the
# puzzle file as the run left it (puzzle.json), its cold-solve fill (fill.json)
# and its session id (session), which is where the hints' author is read.
# tools/salvaged.sh lists and restores them. A copy identical to the id's
# newest is dropped; any older than 14 days is pruned. Never fails the discard.
SALVAGE_ROOT="${SALVAGE_ROOT:-$HOME/.cache/cryptic-teacher/salvage}"
worker_salvage() {
  local id="$1" dir last p runs
  dir="$SALVAGE_ROOT/$id/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$dir" || return 0
  for p in "tools/_ann_$id.json" "tools/_puzzle_$id.json"; do
    [ -s "$p" ] && cp -p "$p" "$dir/"
  done
  p=$(git ls-files -m -o --exclude-standard -- "$(puzzle_spec "$id")" 2>/dev/null | head -1)
  [ -n "$p" ] && [ -s "$p" ] && cp -p "$p" "$dir/puzzle.json"
  runs=$(worker_runs_root 2>/dev/null)
  if [ -n "$(ls -A "$dir")" ]; then
    for p in "$runs"/*/"$id.fill"; do [ -s "$p" ] && cp -p "$p" "$dir/fill.json"; done
    for p in "$runs"/*/"$id.sid"; do [ -s "$p" ] && worker_sid "$p" >"$dir/session"; done
  fi
  last=$(find "$SALVAGE_ROOT/$id" -mindepth 1 -maxdepth 1 -type d ! -path "$dir" | sort | tail -1)
  if [ -z "$(ls -A "$dir")" ] || { [ -n "$last" ] && diff -rq "$last" "$dir" >/dev/null 2>&1; }; then
    rm -rf "$dir"
  fi
  find "$SALVAGE_ROOT" -mindepth 2 -maxdepth 2 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null
  find "$SALVAGE_ROOT" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null
  return 0
}
# Undo a run's edits to one puzzle (restore_puzzle) and its rows of the
# source-correction tables (tools/data/source_*_wrong.json, fetch_puzzle.py):
# back as HEAD has them, then any SOURCE_CLUE_WRONG row left for a clue the
# reverted file does not show. What the run wrote is salvaged first.
discard_puzzle() {
  worker_salvage "$1"
  restore_puzzle "$1"
  { python3 tools/own_rows.py revert "$1" && python3 tools/discard_clue_rows.py "$1"; } ||
    alert "$WORKER_JOB could not put back $1's rows of tools/fetch_puzzle.py after discarding it; the sweep at the end of the run may carry rows its file does not show."
}
# Wait out a held index.lock, and take over one nobody holds. A git command
# keeps index.lock for the length of one command, so one still there after two
# minutes belongs to a git that was killed (10-17 10:04:56: an empty lock, no git
# alive, and independent-12441, azed-2711, book-11022 and cyclops-809 went
# uncommitted until it was removed by hand). Nothing else ever clears it, and
# every stage and commit after it fails the same way. Callers hold ct-index.lock,
# so no sibling run's git is the one waited on. Without a lock path (a stubbed
# git) it only sleeps.
# 10-17 12:27:36: another empty lock, the sixth refusal in a row inside the two
# minutes (sundaytough-167, telegraph-31275, times-29592, sundaytel-3270), with no
# git alive and nothing in the log to say what died. So a lock past
# CT_LOCK_MIN_AGE_SECS (10) is taken over as soon as no git process is alive in
# this worktree (tree_has_live_git); the two minutes remain the limit for a lock
# whose holder cannot be told (no /proc to read the processes' directories).
tree_has_live_git() {
  local top pid comm cwd
  top=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
  top=$(cd "$top" && pwd -P) || return 0
  [ -d /proc/self ] || return 0   # cannot tell whose git it is: assume live
  while read -r pid comm; do
    case "$comm" in git|git-*) ;; *) continue ;; esac
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null) || continue
    case "$cwd/" in "$top"/*) return 0 ;; esac
    tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -qF -- "$top" && return 0
  done < <(ps -eo pid=,comm=)
  return 1
}
clear_stale_index_lock() {
  local lock waited=0 age
  lock=$(git rev-parse --git-path index.lock 2>/dev/null) || lock=""
  [ -n "$lock" ] || { sleep 2; return 0; }
  while [ -e "$lock" ]; do
    age=$(( $(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || stat -f %m "$lock" 2>/dev/null || date +%s) ))
    if [ "$age" -ge 120 ] ||
       { [ "$age" -ge "${CT_LOCK_MIN_AGE_SECS:-10}" ] && ! tree_has_live_git; }; then
      echo "worker: clearing an index.lock from $(date -r "$lock" '+%H:%M:%S') with no live git behind it" >&2
      rm -f "$lock"
      return 0
    fi
    [ "$waited" -lt "${CT_LOCK_WAIT_SECS:-130}" ] || return 0
    sleep 2
    waited=$((waited + 2))
  done
}
# Stage one puzzle for its commit: its pathspecs (puzzle_specs), and its rows
# of fetch_puzzle.py with no sibling's (tools/own_rows.py). On failure nothing
# is left staged, so the next puzzle's commit cannot carry this one.
stage_puzzle() {
  local -a spec
  local try
  puzzle_specs "$1" spec
  # ct-index.lock orders the burn's own runs, but any other git command in
  # this tree (a status, a sync) holds index.lock for a moment, so a refused
  # add is tried again before the run is given up.
  for try in 1 2 3 4 5; do
    git add -A -- "${spec[@]}" && python3 tools/own_rows.py stage "$1" && return 0
    # shellcheck disable=SC2046  # one path per line, none with a space
    git reset -q -- "${spec[@]}" $(python3 tools/own_rows.py paths)
    [ "$try" -lt 5 ] && clear_stale_index_lock
  done
  return 1
}
# stage_puzzle for several puzzles at once (one commit): every one's pathspecs,
# then their rows in one own_rows call, which chains them onto HEAD's file.
stage_puzzles() {   # id...
  local -a spec all=()
  local id try
  for id in "$@"; do
    puzzle_specs "$id" spec
    all+=("${spec[@]}")
  done
  for try in 1 2 3 4 5; do
    git add -A -- "${all[@]}" && python3 tools/own_rows.py stage "$@" && return 0
    # shellcheck disable=SC2046  # one path per line, none with a space
    git reset -q -- "${all[@]}" $(python3 tools/own_rows.py paths)
    [ "$try" -lt 5 ] && clear_stale_index_lock
  done
  return 1
}

# Commit what is staged as "$1" under the index lock and push it. $2.. are the
# pathspecs to unstage if the commit is refused. 0 when committed.
worker_commit() {   # subject paths...
  local subject="$1" out sha try ok=0 rc=0 sigs=0
  local body="${WORKER_COMMIT_BODY:-}"   # set by worker_commit_batch: the ids
  WORKER_COMMIT_BODY=
  shift
  # A status or sync elsewhere in this tree holds index.lock for a moment, as
  # stage_puzzle's add knows; refused once, the staged puzzle used to ride in
  # the next run's commit under that run's name. Only a held lock is retried.
  # The commit names its pathspecs (git's --only form), so whatever else is
  # staged in the shared index, a sibling's file that a git outside
  # ct-index.lock put there (10-17: azed-2778 swept into book-12035), is never
  # in this commit.
  # 10-17: `-- <paths>` takes the WORKING-TREE content of those paths, and the
  # shared correction tables (tools/data/*.json) hold every sibling session's
  # rows there, so puzzle B's rows landed in puzzle A's commit. The commit now
  # comes from the index alone: stage_puzzle(s) put the puzzle files in it
  # and own_rows.py stage put exactly the ids' rows in it (hash-object and
  # update-index, never git add of the whole table). Callers hold ct-index.lock,
  # which is what keeps a sibling's staging out of this index meanwhile.
  for try in 1 2 3 4 5; do
    out=$(git commit -q -m "$(printf '%s\n\n%s%s' "$subject" "${body:+$body$'\n\n'}" "$(python3 tools/provenance.py trailer)")" 2>&1) && { ok=1; break; }
    rc=$?
    # A git killed by a signal (10-17: exit 135, SIGBUS, three finished puzzles
    # left staged, said nothing) most likely had a pack or the index replaced
    # under its mmap by a gc elsewhere; the same commit a few minutes later
    # landed. Tried again, still under ct-index.lock, three tries in all.
    if [ "$rc" -gt 128 ]; then
      sigs=$((sigs + 1))
      [ "$sigs" -lt 3 ] || break
      echo "git commit killed by SIG$(kill -l "$((rc - 128))") (exit $rc); try $((sigs + 1)) of 3 in ${SIGNAL_RETRY_WAIT:-2}s" >&2
      sleep "${SIGNAL_RETRY_WAIT:-2}"
      continue
    fi
    case "$out" in *index.lock*) [ "$try" -lt 5 ] && clear_stale_index_lock ;; *) break ;; esac
  done
  if [ "$ok" = 0 ]; then
    # -q hides "nothing to commit", so a refusal can arrive with no words at all
    # (10-17: the alert for azed-2778 ended at its colon). Say what is known.
    [ -n "$out" ] || out="git commit exited $rc and said nothing; status of $*: $(git --no-optional-locks status --porcelain -- "$@" 2>&1 | tr '\n' ' ')"
    # push_puzzle_commit.sh would find HEAD already on origin and exit 0, so a
    # refused commit has to stop here or the log says "committed".
    git reset -q -- "$@"
    index_unlock
    alert "$WORKER_JOB could not commit $subject, so it does not reach the site until this is fixed: $(printf '%s' "$out" | tail -5)"
    return 1
  fi
  sha=$(git rev-parse HEAD)
  index_unlock
  # One alert text per job, so a GitHub outage that refuses every push
  # wakes the room once, not once per puzzle; the subject goes to the log.
  tools/push_puzzle_commit.sh "$sha" || {
    echo "could not push $subject"
    alert "$WORKER_JOB committed puzzles it could not push — the site will not show them until the run's closing sync pushes them."
  }
  return 0
}

# Blank the model answers ($3...) an annotation found no parse for, and commit
# and push that, so the puzzle is solved again; the run's hints for every other
# clue go in with it when they validate (tools/reopen_answers.py --ran, off the
# run's file copied to $2). The run's view and annotation file go, so the
# retry's view is written afresh and scoped to the clues still lacking a hint
# (annotate_check.to_write). Non-zero, with the file put back, when any step
# fails; the puzzle is then parked like any other.
worker_reopen() {   # id run-file-copy entry...
  local id="$1" ran="$2" out
  shift 2
  rm -f "tools/_ann_$id.json" "tools/_puzzle_$id.json"
  if ! out=$(python3 tools/reopen_answers.py "$id" --ran "$ran" "$@" 2>&1); then
    alert "$WORKER_JOB could not reopen $id's unparsed model answers ($*), so it is parked instead: $(printf '%s' "$out" | tail -3)"
    discard_puzzle "$id"
    return 1
  fi
  local specs
  puzzle_specs "$id" specs
  index_lock
  if ! out=$(git add -A -- "${specs[@]}" 2>&1); then
    git reset -q -- "${specs[@]}"
    index_unlock
    alert "$WORKER_JOB could not stage reopening $id ($*), so it is parked instead: $(printf '%s' "$out" | tail -5)"
    discard_puzzle "$id"
    return 1
  fi
  worker_commit "Reopen $id $*"$'\n\n'"No parse was found for these model answers, so they go back to be solved again, once; the hints that validated stay." \
    "${specs[@]}" || { discard_puzzle "$id"; return 1; }
  echo "  [$id] $out; to be solved again"
}

# Whether puzzle $1's validation ($2, its log) failed only for clues left
# blank (check_every_clue_is_annotated's one line), with a hint elsewhere to
# ship, and the file passes the deploy's rules, which the commit hooks apply:
# there a hole is queued to be annotated again, not an error.
worker_only_blanks() {   # id vlog
  local errs
  errs=$(grep -E '^  ERROR' "$2") || return 1
  grep -qvE '^  ERROR: [0-9]+[AD](,[0-9]+[AD])*: no annotation\.' <<<"$errs" && return 1
  grep -qE '^[^ ].*: [1-9][0-9]*/[0-9]+ annotated' "$2" || return 1
  python3 tools/validate_annotations.py --deploy "$(python3 tools/puzzle_paths.py "$1")" >/dev/null 2>&1
}

# Mark $1, discarded, as awaiting the preamble its entries $2 need
# (tools/await_preamble.py), and commit and push that, so neither picker sends
# it again until a preamble is filed. When any step fails it is parked on its
# inputs instead (tools/failed_inputs.py).
worker_await_preamble() {   # id entries
  local id="$1" out
  local -a specs
  if out=$(python3 tools/await_preamble.py "$id" 2>&1); then
    puzzle_specs "$id" specs
    index_lock
    if out=$(git add -A -- "${specs[@]}" 2>&1); then
      worker_commit "Await the preamble for $id"$'\n\n'"Its annotation left $2 to a preamble the puzzle does not hold, and failed on nothing else." \
        "${specs[@]}" && { echo "  [$id] awaits its preamble ($2)"; return 0; }
    else
      git reset -q -- "${specs[@]}"
      index_unlock
    fi
    discard_puzzle "$id"
  fi
  alert "$WORKER_JOB could not mark $id as awaiting its preamble ($2), so it is parked on its inputs instead: $(printf '%s' "$out" | tail -3)"
  python3 tools/failed_inputs.py record annotate "$id" --judged \
    --reason "definedByPreamble ($2), but the puzzle has no preamble" || true
}

# A run the API refused outright ("safeguards flagged this message",
# [reasoning_extraction]) is not a limit and not a bad puzzle: the conversation
# itself is what is flagged, so resuming it flags again at once, every run, for
# good (10-12: 13 runs, azed-1866/1869/1876, toughie-3351...). Its session, resume
# note, edits and fill are forgotten, so the next launch starts a fresh
# conversation, and the caller must not treat it as a lockout to requeue and
# resume. A fresh conversation (no resume note: the run was not a resume) that is
# flagged a second time on the same puzzle is recorded as a failed input
# instead of looping. The resume note's wording was checked and is not the
# trigger: toughie-3351 was flagged on resume and ran clean fresh.
# 0 when $4's output holds the refusal and it was dealt with; 1 otherwise.
worker_flagged() {   # id notefile sidfile output
  local id="$1" notefile="$2" sidfile="$3" out="$4" flags="${3%.sid}.flags" n resumed=""
  grep -q "safeguards flagged this message" "$out" 2>/dev/null || return 1
  [ -s "$notefile" ] && resumed=1
  local m
  for m in $(worker_bag_ids "$sidfile"); do discard_puzzle "$m"; done
  worker_forget "$sidfile"
  rm -f "$notefile"
  if [ -n "$resumed" ]; then
    echo "  [$id] the API flagged its resumed conversation (safeguards) — session forgotten, the next run starts fresh"
    return 0
  fi
  n=$(( $(cat "$flags" 2>/dev/null || echo 0) + 1 ))
  if [ "$n" -ge 2 ]; then
    rm -f "$flags"
    echo "  [$id] the API flagged a fresh conversation twice (safeguards) — recorded as a failed input"
    python3 tools/failed_inputs.py record annotate "$id" --judged \
      --reason "the API's safeguards flagged two fresh conversations on this puzzle ([reasoning_extraction])" || true
  else
    echo "$n" >"$flags"
    echo "  [$id] the API flagged a fresh conversation (safeguards, $n of 2) — session forgotten, the next run starts fresh"
  fi
  return 0
}

# Whether the run on puzzle $1 took back its own work, printing why; $2 is its
# output, the CLI's final message. A run that cannot pass the check honestly
# is told to annotate nothing (tools/solve_prompt.md), but every check it ran
# has already applied its tools/_ann_<id>.json to the puzzle file, and its
# permissions refuse git. So it runs `annotate_check.py <id> --withdraw`,
# which leaves tools/_withdrawn_<id>.txt, and the harness puts the file back
# (worker_withdraw). A run whose last words ask for a git command to undo its
# edits is taken at its word the same way: genius-268 (10-13) rejected its own
# run, was refused `git checkout`, and its 29 hints and guessed fills were
# committed as "Annotate genius-268". Lowercase only, so an answer in a
# confidence line (RESET, RESTORED) is not read as a request.
worker_withdrawn() {   # id [output]
  local marker="tools/_withdrawn_$1.txt" asked
  if [ -e "$marker" ]; then
    echo "it ran annotate_check.py --withdraw: $(grep -v '^[[:space:]]*$' "$marker" | head -1 | cut -c1-200)"
    return 0
  fi
  [ -n "${2:-}" ] && [ -s "$2" ] || return 1
  asked=$(grep -E -m1 '\bgit (checkout|restore|reset|stash|clean)\b' "$2") || return 1
  echo "its last words asked for a git revert: $(printf '%s' "$asked" | sed 's/^[[:space:]]*//' | cut -c1-200)"
}

# Undo everything a withdrawn run wrote for puzzle $1 ($2: why, from
# worker_withdrawn): the puzzle file and its rows go back as committed
# (discard_puzzle, which salvages them first) and its annotation file goes, so
# nothing it took back reaches a commit, a reopen or a resume. It is recorded
# against the puzzle's inputs: the run said it cannot do this honestly, so the
# same work is not bought again until its clues change or its key is filed.
worker_withdraw() {   # id why
  echo "  [$1] the run withdrew its own work, so nothing it wrote ships — $2"
  discard_puzzle "$1"
  rm -f "tools/_ann_$1.json" "tools/_withdrawn_$1.txt"
  python3 tools/failed_inputs.py record annotate "$1" --judged \
    --reason "the run withdrew its own work: $2" || true
}

# A run that failed or was stopped. One cut off by a lockout usually leaves
# real work behind: some clues annotated, the rest untouched. That file fails
# validation (its blank clues), so validation cannot be the test: throwing it
# away means paying for those clues again, so any file that still parses is
# kept. Only a half-written one, the run died mid-write, is put back. Either way
# the conversation (sid file $4) is resumed by the retry, since its reasoning is
# the expensive part: the note written to $3 says what it finds on disk.
# $5 says how it was stopped; $6 set means master changed the puzzle meanwhile,
# so nothing it wrote to the puzzle came back. 0 when its edits were kept.
worker_failed() {   # id what notefile sidfile [how] [moved]
  local m tmp kept=1 note=""
  if [ ! -s "${4%.sid}.bag" ]; then _worker_failed_one "$@"; return; fi
  # A bag: each puzzle still listed is judged on its own, and the notes go to
  # the one conversation as one note.
  tmp=$(mktemp "${TMPDIR:-/tmp}/cryptic-bagnote.XXXXXX")
  for m in $(worker_bag_ids "$4"); do
    : >"$tmp"
    if _worker_failed_one "$m" "$2" "$tmp" "$(dirname "$4")/$m.sid" "${5:-}" "${6:-}"; then kept=0; fi
    if [ -s "$tmp" ]; then note="${note:+$note$'\n\n'}[$m] $(cat "$tmp")"; else worker_bag_drop "$4" "$m"; fi
  done
  rm -f "$tmp"
  if [ -n "$note" ]; then
    printf '%s\n' "This session holds several puzzles; for each one:"$'\n'"$note" >"$3"
  else
    rm -f "$3"
    worker_forget "$4"
  fi
  return $kept
}
_worker_failed_one() {   # id what notefile sidfile [how] [moved]
  local id="$1" what="$2" how="${5:-were cut off by a usage limit, which has since cleared}" seen intact="" why
  # A run that withdrew is not resumed into the edits it took back.
  if why=$(worker_withdrawn "$id"); then
    worker_withdraw "$id" "$why"
    rm -f "$3"
    worker_forget "$4"
    return 1
  fi
  # What the retry is told to look at: the annotate run's copy, never the
  # puzzle itself, which names the blog.
  seen=$(python3 tools/puzzle_paths.py "$id")
  [ "$what" = Annotate ] && seen="tools/_puzzle_$id.json"
  if [ -z "${6:-}" ] && [ -n "$(git --no-optional-locks status --porcelain -- "$(puzzle_spec "$id")")" ] &&
     python3 -c 'import glob,json,sys; [json.load(open(f)) for f in glob.glob(sys.argv[1])]' "$(puzzle_spec "$id")" >/dev/null 2>&1; then
    echo "  [$id] run stopped — keeping what it finished, the file still parses"
    printf '%s\n' "You $how. Your edits to $seen are exactly as you left them. Pick up where you stopped, finish the task you were given, and run python3 tools/annotate_check.py $id until it reports clean. Do not commit." >"$3"
    return 0
  fi
  echo "  [$id] run stopped — discarding its changes to the puzzle, keeping its conversation"
  discard_puzzle "$id"
  [ -s "tools/_ann_$id.json" ] && intact="tools/_ann_$id.json"
  [ -s "${4%.sid}.fill" ] && intact="${intact:+$intact and }${4%.sid}.fill"
  printf '%s\n' "You $how. The puzzle file is now as committed on master${6:+, which changed it while you were stopped, so read it again first}; any edits you had made to it are gone.${intact:+ $intact is as you left it.} What you worked out is still above: redo from it whatever is missing rather than working it out again, finish the task you were given, and run python3 tools/annotate_check.py $id until it reports clean. Do not commit." >"$3"
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
  if [ -s "${3%.sid}.bag" ]; then worker_finish_bag "$@"; return; fi
  _worker_finish "$@"
  local rc=$?
  # 3 (only with WORKER_KEEP_CUTOFF_FIX set): the fix run was cut off (a limit, a crash) and the file still fails, so
  # the conversation and its scratch are kept for the caller to resume.
  [ "$rc" -eq 3 ] && return 3
  worker_forget "$3"
  worker_clean "$1"
  return $rc
}

# worker_finish for a bag: each puzzle the bag still lists is validated and
# committed on its own, as a single run's would be, and one that fails costs
# only itself. Returns 0 when every puzzle was dealt with; the ids among them
# whose unparsed answers were reopened to be solved again (_worker_finish's 2)
# are left in WORKER_BAG_AGAIN. Returns 3 as _worker_finish does for a cut-off
# fix run, with that puzzle and those after it still on the bag and the
# conversation kept. Each puzzle gets its own copy of the log, so one's fix run
# does not overwrite another's.
worker_finish_bag() {   # leader what sidfile log
  local what="$2" sidfile="$3" log="$4" m rc
  local -a seen=()
  WORKER_BAG_AGAIN=""
  WORKER_BATCH_IDS=()
  WORKER_BATCH_ON=1
  for m in $(worker_bag_ids "$sidfile"); do
    cp "$log" "$log.$m" 2>/dev/null || : >"$log.$m"
    _worker_finish "$m" "$what" "$sidfile" "$log.$m"
    rc=$?
    rm -f "$log.$m"
    if [ "$rc" -eq 3 ]; then
      # Cut off: what validated so far is committed now, the rest stays bagged.
      WORKER_BATCH_ON=""
      worker_commit_batch "$what"
      worker_bag_drop_all "$sidfile" "${seen[@]}"
      return 3
    fi
    [ "$rc" -eq 2 ] && WORKER_BAG_AGAIN="${WORKER_BAG_AGAIN:+$WORKER_BAG_AGAIN }$m"
    worker_clean "$m"
    seen+=("$m")
  done
  WORKER_BATCH_ON=""
  worker_commit_batch "$what"
  worker_bag_drop_all "$sidfile" "${seen[@]}"
  worker_forget "$sidfile"
  return 0
}
# Take each id off the bag: dealt with, committed (or left in the tree for the
# uncommitted-puzzle sweep) once the batch's one commit has been tried.
worker_bag_drop_all() {   # sidfile id...
  local sidfile="$1" m
  shift
  for m in "$@"; do worker_bag_drop "$sidfile" "$m"; done
}

# Delete the scratch a finished puzzle left in tools/: its payloads
# (_ann_<id>.json, _puzzle_<id>.json) and whatever else the run named after it
# (_fill_<id>.json, _patch_<id>.json, _withdrawn_<id>.txt...). Done with once
# the puzzle is committed or discarded; a discard has salvaged them already
# (worker_salvage). "_<id>." so cryptic-301 never matches cryptic-30111's.
# Without this they waited for the sweep at the very end of a run, which a
# burn that re-execs and gets stopped rarely reaches (2,427 of them, 10-14).
worker_clean() {   # id
  rm -f tools/_*_"$1".*
}

# Delete the unnamed scratch scripts and dumps runs write in tools/ (_peek3.py,
# _w2.json) once older than $1 minutes (default 360): no run reads another's,
# and a run that old has finished. The per-puzzle payloads are worker_clean's,
# since a run resumed after a nap still needs its own. Never a tracked file.
worker_sweep_scratch() {   # [minutes]
  local p
  find tools -maxdepth 1 -type f -name '_*' ! -name '_ann_*' ! -name '_puzzle_*' \
    ! -name '_withdrawn_*' -mmin +"${1:-360}" 2>/dev/null |
    while IFS= read -r p; do
      git ls-files --error-unmatch -- "$p" >/dev/null 2>&1 || rm -f -- "$p"
    done
  return 0
}
_worker_finish() {
  local id="$1" what="$2" sidfile="$3" log="$4" vlog file reopen ran loss wants pending="" why fix_rc=0 partial="" verdict="" first_ok=""
  # A run that took its work back ships none of it, however it validates.
  if why=$(worker_withdrawn "$id" "$log"); then
    worker_withdraw "$id" "$why"
    return 1
  fi
  vlog="$(mktemp "${TMPDIR:-/tmp}/cryptic-validate.XXXXXX")"
  if ! python3 tools/validate_annotations.py "$id" >"$vlog" 2>&1; then
    file=$(python3 tools/puzzle_paths.py "$id")
    echo "  [$id] did not validate — handing the errors back rather than discarding the puzzle"
    local fix
    fix=$(printf '%s\n\n%s\n\n%s\n' "$file does not validate:" "$(grep -E '^  ERROR' "$vlog")" \
      "Fix those clues in $file and nothing else, following tools/annotate_prompt.md, then run python3 tools/annotate_check.py $id until it reports clean. Do not commit. If they cannot be fixed honestly, run python3 tools/annotate_check.py $id --withdraw \"<why>\" instead and stop: the puzzle file is put back for you.")
    # Even a fix run the limit cuts off may have landed its edit, so the second
    # validation runs either way and decides on what is on disk.
    declare -F on_fix_run >/dev/null && on_fix_run 1
    worker_annotate "$id" "$log" "$sidfile" "$fix" "$fix" || fix_rc=$?
    declare -F on_fix_run >/dev/null && on_fix_run 0
    # The fix run may take the work back instead (genius-268, 10-13: the
    # validator passed what the run had asked to revert, and it shipped).
    if why=$(worker_withdrawn "$id" "$log"); then
      rm -f "$vlog"
      worker_withdraw "$id" "$why"
      return 1
    fi
  else
    # Passed on the first look and nothing has touched the file since: a
    # second pass would parse and check the same input again (~2 CPU-s).
    first_ok=1
  fi
  if [ -z "$first_ok" ] && ! python3 tools/validate_annotations.py "$id" >"$vlog" 2>&1; then
    tail -5 "$vlog"
    # The fix run died before it could answer (not the API's refusal, which
    # worker_flagged-style handling keeps fresh): its conversation is not
    # evidence the clues cannot be fixed, so it is kept and resumed, not
    # discarded and bought again from scratch.
    if [ "$fix_rc" -ne 0 ] && [ -n "${WORKER_KEEP_CUTOFF_FIX:-}" ] && ! grep -q "safeguards flagged this message" "$log" 2>/dev/null &&
       session_exists "$(worker_sid "$sidfile")"; then
      echo "  [$id] its fix run was cut off (exit $fix_rc) and the file still fails — keeping the conversation to resume"
      rm -f "$vlog"
      return 3
    fi
    # A model's answer the run could not parse may be the wrong word, and a
    # failure record would hold it until its inputs change, which is never. So
    # those answers are blanked and solved again instead, once per entry, the
    # other clues keeping the hints the run wrote for them
    # (tools/reopen_answers.py); read before the discard, off the run's file.
    # A puzzle solved in this same run has no committed solve, so the run's
    # answers are copied aside before the discard and reopened from there.
    reopen=$(python3 tools/reopen_answers.py "$id" --which) || reopen=""
    if [ -n "$reopen" ]; then
      ran="$vlog.ran.json"
      cp "$(python3 tools/puzzle_paths.py "$id")" "$ran"
      discard_puzzle "$id"
      # shellcheck disable=SC2086 # $reopen is a list of entry ids
      worker_reopen "$id" "$ran" $reopen && { rm -f "$vlog" "$ran"; return 2; }
      rm -f "$ran"
    fi
    # Answers left to a preamble the puzzle lacks, and nothing else wrong:
    # another run would fail the same way, and no change to its clues mends
    # it, so the puzzle is marked to await its preamble instead of parked.
    wants=$(python3 tools/await_preamble.py "$id" --which) || wants=""
    if [ -n "$wants" ]; then
      discard_puzzle "$id"
      rm -f "$vlog"
      worker_await_preamble "$id" "$wants"
      return 1
    fi
    # Wrong only in clues left blank, and nothing reopened them: the hints
    # that did validate ship, and the blanks stay pending (the deploy's rules:
    # a hole is queued, the puzzle indexes as unannotated). One clue no run
    # can parse used to discard every other hint with it (nation-3405, 10-12).
    # Recorded against its inputs as a parked puzzle is, so the hole is not
    # bought again until a person changes the clue.
    if [ -z "$reopen" ] && worker_only_blanks "$id" "$vlog"; then
      pending=$(grep -E '^  ERROR' "$vlog" | head -1 | cut -c1-200)
      echo "  [$id] only blank clues failed — shipping the hints that validated, the blanks left pending"
    fi
    # Clues that still fail after the fix run cost only their own hints
    # (tools/drop_failed_clues.py): the rest ship. The first time, the dropped
    # clues are simply due again (annotate_check.to_write), so the planner sends
    # them later as a scoped tail; the puzzle's second such failure parks it on
    # its inputs like any other (discard_alert's count, shared with a discard).
    # An error that names no clue is the puzzle's, and discards it as before.
    local ddir dropped="" pfile; verdict=alert
    if [ -z "$pending" ] && [ -z "$reopen" ]; then
      pfile=$(python3 tools/puzzle_paths.py "$id")
      cp "$vlog" "$vlog.first"
      cp "$pfile" "$vlog.file"
      if dropped=$(python3 tools/drop_failed_clues.py "$id" 2>/dev/null) && [ -n "$dropped" ] &&
         { python3 tools/validate_annotations.py "$id" >"$vlog" 2>&1 || true; worker_only_blanks "$id" "$vlog"; }; then
        ddir="$(worker_runs_root)/discards"
        verdict=$(python3 tools/discard_alert.py judge "$id" "$vlog.first" --dir "$ddir" 2>/dev/null) || verdict=alert
        partial=1
        pending=$(grep -E '^  ERROR' "$vlog.first" | head -1 | cut -c1-200)
        echo "  [$id] clues still failing ($dropped) dropped — shipping the hints that validated, those clues left due"
        [ "$verdict" != alert ] || alert "$what $id shipped without $dropped, which failed twice, so that puzzle is parked on them: $pending"
      else
        # Put the run's file back as it was, for the discard below to salvage.
        cp "$vlog.file" "$pfile"
        cp "$vlog.first" "$vlog"
        dropped=""
      fi
      rm -f "$vlog.first" "$vlog.file"
    fi
    if [ -z "$pending" ]; then
      # Whether anyone can act on this (tools/discard_alert.py): a puzzle that
      # awaits a preamble is parked silently; a first discard is retried by the
      # next pick, unparked and unannounced; a second is a ledger line unless
      # its error class is new.
      ddir="$(worker_runs_root)/discards"
      verdict=$(python3 tools/discard_alert.py judge "$id" "$vlog" --dir "$ddir" 2>/dev/null) || verdict=alert
      if [ "$verdict" = retry ]; then
        echo "  [$id] discarded once — left unparked for one more try, no alert"
        discard_puzzle "$id"
        rm -f "$vlog"
        return 1
      fi
    fi
    if [ -z "$pending" ]; then
      # Parked: the work is thrown away and the puzzle stays unannotated until
      # its inputs change, which only a person mending the clue or answer does,
      # so this is said out loud. Quoting the failure line verbatim marks it
      # claimed for alert.sh.
      [ "$verdict" = alert ] && alert "$what $id was discarded — it did not validate, so that puzzle stays unannotated:"$'\n'"VALIDATION FAILED after $what $id — discarding that puzzle's changes"$'\n'"\`\`\`"$'\n'"$(grep -E '^  ERROR' "$vlog" | head -5)"$'\n'"\`\`\`"
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
  fi
  rm -f "$vlog"
  # Solved-but-short is not a failure: the nulled clues ship as "answers only".
  # Say so, once, per puzzle.
  loss=$(python3 tools/check_annotation_loss.py "$id" 2>&1) || [ -n "$partial" ] ||
    alert "$WORKER_JOB left clues blank — $loss. They ship with no teaching ladder."
  echo "$loss"
  # A printedClue this run filed on an OCR'd puzzle asks its scan to be read
  # again, so the OCR learns what the annotator mended.
  python3 tools/annotate_check.py --reread "$id" || true
  if [ -z "$(git --no-optional-locks status --porcelain -- "$(puzzle_spec "$id")")" ]; then
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
  # a new copy beside the old one, and a cold solve's promoted clues-only file
  # goes in as its deletion. Its rows of fetch_puzzle.py go with it, and only
  # its own: a corrected clue is valid only beside its SOURCE_CLUE_WRONG row,
  # and siblings still in flight file theirs into the same file.
  # A bag's finish (WORKER_BATCH_ON set) only queues the puzzle: worker_finish_bag
  # commits everything that validated in one commit (worker_commit_batch).
  if [ -n "${WORKER_BATCH_ON:-}" ]; then
    WORKER_BATCH_IDS+=("$id")
    WORKER_BATCH_POST[$id]="${partial:+p}|$verdict|$pending"
    return 0
  fi
  index_lock
  local out
  local -a spec
  puzzle_specs "$id" spec
  if ! out=$(stage_puzzle "$id" 2>&1); then
    index_unlock
    alert "$WORKER_JOB could not stage $id's rows of tools/fetch_puzzle.py, so $what $id is not committed: $(printf '%s' "$out" | tail -5)"
    return 1
  fi
  # shellcheck disable=SC2046  # one path per line, none with a space
  worker_commit "$what $id" "${spec[@]}" $(python3 tools/own_rows.py paths) || return 1
  worker_settle "$id" "${partial:+p}" "$verdict" "$pending"
  echo "committed $what $id"
  return 0
}

# What a committed puzzle changes in the ledgers: parked on what is still
# failing, or cleared. $2 is "p" when clues were dropped to ship it.
worker_settle() {   # id partial verdict pending
  if [ -n "$2" ] && [ "$3" = retry ]; then
    : # Left unparked: the dropped clues are due, and the next pick is their tail.
  elif [ -n "$4" ]; then
    python3 tools/failed_inputs.py record annotate "$1" --judged --reason "$4" || true
  else
    python3 tools/failed_inputs.py clear annotate "$1" >/dev/null
    python3 tools/discard_alert.py clear "$1" --dir "$(worker_runs_root)/discards" || true
  fi
}

# One commit for every puzzle a bag finished and queued in WORKER_BATCH_IDS:
# "Annotate 9 puzzles" with the ids in the body, or the plain "Annotate id" for one. Their
# files and their rows of the shared tables are staged together, under the
# index lock, so the commit is the whole batch or nothing; push_puzzle_commit.sh
# then publishes it as one (its conflict handling is per puzzle file). On a
# failed stage or commit the puzzles stay in the tree, uncommitted, as a single
# failed commit leaves one. Empties the queue either way.
worker_commit_batch() {   # what
  local what="$1" out id subject post
  local -a ids=("${WORKER_BATCH_IDS[@]}") specs=() one
  WORKER_BATCH_IDS=()
  [ "${#ids[@]}" -gt 0 ] || return 0
  index_lock
  for id in "${ids[@]}"; do
    puzzle_specs "$id" one
    specs+=("${one[@]}")
  done
  if ! out=$(stage_puzzles "${ids[@]}" 2>&1); then
    index_unlock
    alert "$WORKER_JOB could not stage ${ids[*]}'s files or rows of tools/fetch_puzzle.py, so $what ${ids[*]} is not committed: $(printf '%s' "$out" | tail -5)"
    return 1
  fi
  # The subject names the puzzles whose file this commit changes: one whose
  # file is already as HEAD has it (a sibling's commit swept it in, or the run
  # changed nothing) is settled below all the same but not listed (164738e46f2
  # named 20 puzzles and changed only the queue file).
  local -a named=()
  for id in "${ids[@]}"; do
    puzzle_specs "$id" one
    git --no-optional-locks diff --cached --quiet -- "${one[@]}" || named+=("$id")
  done
  if [ "${#named[@]}" -eq 1 ]; then subject="$what ${named[0]}"
  elif [ "${#named[@]}" -eq 0 ]; then subject="$what: queue rows of ${#ids[@]} puzzles, no puzzle file changed"
  else
    # Git convention (Paul 10-20): a short subject, the ids in the body.
    subject="$what ${#named[@]} puzzles"
    WORKER_COMMIT_BODY="$(printf '%s' "${named[*]}" | fold -s -w 72)"
  fi
  # shellcheck disable=SC2046  # one path per line, none with a space
  worker_commit "$subject" "${specs[@]}" $(python3 tools/own_rows.py paths) || return 1
  for id in "${ids[@]}"; do
    post="${WORKER_BATCH_POST[$id]}"
    worker_settle "$id" "${post%%|*}" "$(cut -d'|' -f2 <<<"$post")" "${post#*|*|}"
    echo "committed $what $id"
  done
  return 0
}
