#!/bin/bash
# Burn the tail of the weekly usage window on backfills, just before it resets.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. Whatever is left when the weekly window turns over is simply gone.
# daily_update.sh deliberately refuses to annotate above ANNOTATE_MAX_WEEKLY_PCT
# (50%) because a crossword backlog is never worth being rate-limited for real
# work — but that reasoning stops applying at the end of the window, when there
# is no real work left to protect. So this job runs with NO usage gate at all,
# on purpose, and ONLY then.
#
# "Only then" is load-bearing and was wrong for its first week: the job is fired
# hourly and almost always exits immediately, because whether this is the hour
# is decided by asking the usage API when the window resets, not by the time on
# the clock. See the check below.
#
# HOW MUCH IS LEFT DECIDES BOTH THE START AND THE WIDTH. Two hours of one
# annotation at a time spends a few percent, so a week that ends with tens of
# percent unspent ends that way however faithfully this job runs. Both numbers
# are arithmetic on the remainder and on rates this job measures for itself —
# tools/prereset_plan.py, which is where they are explained and tested.
#
# The remainder can only be spent one FIVE-hour window at a time: saturate that
# limit and nothing more can be bought at any width until it turns over. So the
# start is a count, not a rate — how many five-hour windows the remainder needs,
# times five hours — and this job expects to be locked out once per window it
# asked for. A lockout is waited out rather than read as the week being over,
# and the wave after it picks up where the last one stopped.
#
# AND IT NEVER RUNS AHEAD OF THAT COUNT. The count is re-asked before every wave,
# so the moment spending has bought back enough slack the job stands down and
# exits, and the hourly fire restarts it when it falls behind again. That is the
# difference between spending what the week was going to lose and simply taking
# it early: quota spent on Monday is quota real work cannot have on Tuesday, and
# whether Monday was needed at all is only knowable on Monday.
#
# Paul, 2026-08-02: "right before my weekly inference resets you should spend
# whatever is left on backfills."
#
# What it backfills, in priority order:
#   1. Un-annotated puzzles, NEWEST FIRST BY DATE, across every series at once.
#      A solver arriving today is looking at this week's puzzles, so this week's
#      puzzles are the ones worth spending on, whoever printed them.
#   2. Every field in tools/annotation_backlog.json — definitionFit, the
#      one-sentence "why does the answer mean the definition", and
#      indicatorNotes, "why is THAT word the indicator". New puzzles are
#      required to carry these; the file is the list of puzzles annotated
#      before each rule existed, and draining one tightens the rule on it
#      forever. The fields are read from the file, so this job needs no edit
#      when the next rule lands.
#
# It stops on the FIRST failed claude run rather than retrying. Out here that
# almost always means the window is finally exhausted, which is exactly the
# state this job is trying to reach; hammering it after that just produces a
# log full of identical errors.
#
# Install: LaunchAgent ~/Library/LaunchAgents/com.pt.cryptic-teacher-prereset.plist,
# NOT crontab — same reason as daily_update.sh. The `claude` CLI keeps its OAuth
# credentials in the *login* keychain, which cron cannot unlock.
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pt.cryptic-teacher-prereset.plist
#   launchctl kickstart -k gui/$(id -u)/com.pt.cryptic-teacher-prereset   # run it now

set -uo pipefail
# A checkout of its own, so an hour of unmetered annotation cannot collide with
# the 06:15 job or with somebody editing the repo. See tools/nightly_worktree.sh.
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="$HOME/.local/bin:$HOME/.claude/local:/usr/local/bin:/opt/homebrew/bin:$PATH"
# Without this the CLI reads the legacy un-suffixed keychain entry, which a
# file-based /login emptied on 2026-07-31, and every run dies on "Failed to
# authenticate: OAuth session expired and could not be refreshed". See the longer
# note in daily_update.sh.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
. "$REPO/tools/alert.sh"

# This run's own output, so the exit trap can report any failure line nobody
# wrote an alert for. See alert_run_failures in alert.sh.
RUN_LOG="$(mktemp -t cryptic-prereset)"
exec > >(tee -a "$RUN_LOG") 2>&1

# Kept in step with daily_update.sh — Opus since 2026-08-09, benchmarked against
# Fable on 30078 (STYLE.md). Matching quality at a third the cost matters more
# here than anywhere: this script exists to burn the tail of the weekly window,
# so a cheaper annotator is straightforwardly more puzzles per reset.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
. "$REPO/tools/annotate_model.sh"
MODEL="$ANNOTATE_MODEL"
# How close to the reset counts as "the end of the week" — five hours for every
# five-hour window the remainder needs, so a nearly-spent week gets one and a
# wholly unspent one gets eight. Zero when there is nothing left, which keeps the
# gate shut: no positive number of hours until reset is ever within zero.
WINDOW_HOURS="${WINDOW_HOURS:-$(python3 tools/prereset_plan.py --window-hours 2>/dev/null || echo 5)}"
FORCE_HOURS="${FORCE_HOURS:-1}"
# Above this the weekly window really is gone and a failing run means it. Below
# it, a failure is the FIVE-hour window instead, which clears by itself.
#
# The CLI's own words do not distinguish them. With pay-as-you-go set to $0 it
# says "You've hit your monthly spend limit" for BOTH — there is no dollar cap
# involved, only a plan limit with no paid overflow to fall through to. So which
# limit was hit is read off the seven-day number here, never off the message.
EXHAUSTED="${EXHAUSTED:-97}"
# How much of each FIVE-hour window is kept back for whoever else is on this
# account — but only while they are actually using it. The whole weekly
# remainder is still meant to be spent, so an empty room gets the reserve too.
# See bridge_busy and the note in after_wave.
SESSION_RESERVE_PCT="${SESSION_RESERVE_PCT:-25}"
BRIDGE_DIR="${BRIDGE_DIR:-$HOME/.claude/projects/-Users-pt}"
BRIDGE_IDLE_MIN="${BRIDGE_IDLE_MIN:-60}"
# The reserve is DEFERRED, never forfeited. A five-hour window that turns over
# with room left on it has thrown that room away for good, so in the last of its
# minutes the reserve gets spent whether or not anyone is on the bridge.
#
# How many minutes is NOT a constant: it is however long the reserve takes to
# spend at the width in use, which prereset_plan measures. This number is also
# exactly how long the lockout it causes can last, so a constant is wrong in
# both directions — too small strands quota on an expiring window, too big takes
# an account Paul is using and hands it nothing to show for the difference. An
# env override is honoured as-is and never refreshed.
SESSION_ENDGAME_FIXED=$([ -n "${SESSION_ENDGAME_MIN:-}" ] && echo 1 || echo 0)
SESSION_ENDGAME_MIN="${SESSION_ENDGAME_MIN:-40}"

# Re-derive the endgame from the width the last wave actually ran at. Silent on
# failure: the previous value is a better answer than no gate at all.
refresh_endgame() {
  local got
  [ "$SESSION_ENDGAME_FIXED" = 1 ] && return 0
  got=$(python3 tools/prereset_plan.py --endgame-min "$SESSION_RESERVE_PCT" "${1:-1}" 2>/dev/null)
  case "$got" in ''|*[!0-9]*) return 0 ;; esac
  SESSION_ENDGAME_MIN="$got"
}
# One nap per five-hour window this job asked for is the PLAN, not a failure, so
# the allowance is that count with slack rather than a constant. A constant that
# is smaller than the number of windows ends the job in the middle of the run it
# scheduled, with the remainder it was started for still sitting there. Each nap
# is capped at the deadline regardless, so this only bounds waves failing fast
# for some reason other than a lockout — it is not a budget to ration.
MAX_NAPS="${MAX_NAPS:-$(python3 tools/prereset_plan.py --windows 2>/dev/null || echo 6)}"
MAX_NAPS=$((MAX_NAPS + 2))
# DRY_RUN=1 walks the whole job — gate, queue order, wave widths, deadline —
# without calling claude, touching git or rebuilding anything. This job spends
# ungated inference in parallel and cannot be rehearsed any other way; the first
# version of it ran seven ungated nights a week and read as healthy in the log.
DRY_RUN="${DRY_RUN:-0}"

echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') ==="

# One at a time. launchd will not start a second copy of its own job, but this
# now runs for hours rather than one, so an hourly fire and a hand-run FORCE=1
# overlap easily — and two copies would double the width nobody asked for and
# race each other's commits in the one git index. mkdir is the atomic part.
LOCK="$REPO/.prereset.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "another pre-reset backfill is running (started $(date -r "$LOCK" '+%H:%M')) — leaving it alone"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null; sleep 1; alert_run_failures "$RUN_LOG"; rm -f "$RUN_LOG"' EXIT
# Session ids and resume notes belong to the run that wrote them. Left behind by
# a run that stopped before its retry, they would have tonight's first attempt
# resume a conversation about a worktree that has since been reset out from
# under it — and be told to carry on from edits that are no longer there.
rm -f /tmp/ct-prereset-*.sid /tmp/ct-prereset-*.resume

# THE WHOLE JOB HANGS ON THIS CHECK. Everything below runs with no usage gate
# whatsoever, which is only defensible in the hour before quota that cannot roll
# over evaporates. The first version decided it was that hour by looking at the
# clock — 04:00 to 04:55, hard-coded — and was scheduled daily, so an ungated
# hour of inference ran SEVEN nights a week instead of one. That is what carried
# the week to 68% by Friday and left the 06:15 job crashing into rate limits it
# had itself created, while the log cheerfully said "past 04:55 — stopping" as
# though the design were working.
#
# The reset is not a time of day to be guessed at. It is a timestamp the usage
# API hands over on request, it moves with daylight saving and with whatever
# Anthropic does to the account, and a fitted constant standing in for a
# queryable fact is always the wrong model. So: ask, and if the answer is "not
# yet", exit having spent nothing. This job is now a poll, not an appointment —
# see the plist, which fires it hourly precisely because the answer moves.
#
# Exit 3 means the answer is derived rather than read: the API had turned the
# window over without re-stamping it, so the number is one window length past
# the reset we last saw. That is trustworthy in exactly one direction. It can
# say "not the pre-reset hour" — the window just started, so of course it isn't
# — and it must never say "spend", because spending an ungated hour on an
# inferred reset time is the hard-coded 04:00 all over again, aimed at a guess.
resets_in=$(python3 tools/weekly_usage.py --resets-in)
resets_rc=$?
if [ -z "$resets_in" ]; then
  alert "pre-reset backfill can't read when the weekly window resets, so it can't tell whether this is the hour to spend the remainder. Skipped — see .prereset.log. Nothing is being backfilled until this reads again."
  exit 1
fi
if [ "$resets_rc" = 3 ] && awk "BEGIN{exit !($resets_in <= $WINDOW_HOURS)}"; then
  alert "pre-reset backfill thinks the weekly window resets in ${resets_in}h, but that is inferred from a reset the API stopped reporting rather than read from it — and it will not spend an ungated hour of inference on a guess. Skipped; see .prereset.log."
  exit 1
fi

if [ "${FORCE:-0}" = 1 ]; then
  echo "FORCE=1 — ignoring the ${resets_in}h until reset, capped at ${FORCE_HOURS}h"
  budget_hours="$FORCE_HOURS"
elif awk "BEGIN{exit !($resets_in > $WINDOW_HOURS)}"; then
  echo "weekly window resets in ${resets_in}h (more than ${WINDOW_HOURS}h away)"
  echo "not the pre-reset hour — nothing spent. Set FORCE=1 to override."
  exit 0
else
  echo "weekly window resets in ${resets_in}h — spending the remainder"
  budget_hours="$resets_in"
fi

# Stop five minutes short of the turnover: past it we would be spending the NEW
# week's quota on a backlog, which is the opposite of the point. Computed as an
# epoch second rather than compared as an "HH:MM" string, which used to need a
# special case for runs that started after midnight-ish and got it subtly wrong.
STOP_AT=$(python3 -c "import sys,time; print(int(time.time() + float(sys.argv[1])*3600 - 300))" "$budget_hours")
echo "deadline $(date -r "$STOP_AT" '+%H:%M')"
past_deadline() {
  [ "$(date +%s)" -ge "$STOP_AT" ]
}

# NEVER SPEND A WINDOW EARLIER THAN THE REMAINDER REQUIRES. The startup gate asks
# once whether we are inside the last N five-hour windows; this asks again before
# every wave, against what is left NOW. Spending shrinks the remainder, a smaller
# remainder needs fewer windows, and fewer windows pull the start time back toward
# the reset — so a job that gets ahead of itself notices and stops. Real work
# spending the same quota has the same effect, which is the point: this job takes
# only what the week was going to lose anyway, and takes it as late as it can.
#
# Standing down means EXITING, not sleeping. The plist fires hourly and re-decides
# with a fresh reading; a process asleep for five hours on a plan made before it
# slept is the hard-coded 04:00 appointment wearing a different hat.
#
# Paul, 2026-08-23: "I also don't want it to pre spend. So make sure it doesn't
# spend on Monday unless it needs to."
still_behind() {
  if [ "${FORCE:-0}" = 1 ]; then return 0; fi
  # verdict is initialised, not just declared: `local verdict` leaves it UNSET,
  # and set -u turns the unreadable-API path into an unbound-variable abort.
  local hours verdict=""
  hours=$(python3 tools/weekly_usage.py --resets-in 2>/dev/null)
  [ -n "$hours" ] && verdict=$(python3 tools/prereset_plan.py --behind "$hours" 2>/dev/null)
  # Only an explicit "no" stops the run. A reading we failed to take is not a
  # reason to stop: the deadline still bounds us, and reading an unreachable API
  # as "we are ahead" strands the whole remainder on the night it exists for.
  [ "$verdict" != "no" ]
}
stand_down() {
  echo "back on schedule — what is left fits in the windows that remain; standing down"
  echo "the hourly fire will pick it up again when it falls behind"
}

# Hours between two epoch seconds. A function because both callers used to build
# the awk program by string interpolation and both got it wrong the same way.
hours_between() {
  awk -v a="$1" -v b="$2" 'BEGIN{printf "%.3f", (b - a) / 3600}'
}

# Is anyone on the bridge right now? Their conversations are the transcripts in
# BRIDGE_DIR, touched on every turn. This job's own claude runs cannot be
# mistaken for company: they run from the worktree, so the CLI files them under
# a project directory named after it instead.
_bridge_warned=0
bridge_busy() {
  if [ ! -d "$BRIDGE_DIR" ]; then
    # Unreadable means BUSY. Under-spending the remainder is a line in this log;
    # taking the window out from under a conversation is a surprise lockout.
    if [ "$_bridge_warned" = 0 ]; then
      _bridge_warned=1
      alert "pre-reset backfill cannot see the bridge transcripts at $BRIDGE_DIR, so it cannot tell whether anyone is using the account. It is holding ${SESSION_RESERVE_PCT}% of every five-hour window back rather than risk a lockout, which means the weekly remainder will be under-spent until that path is right."
    fi
    return 0
  fi
  [ -n "$(find "$BRIDGE_DIR" -maxdepth 1 -name '*.jsonl' -mmin "-$BRIDGE_IDLE_MIN" 2>/dev/null | head -1)" ]
}

# Minutes until the five-hour window turns over. Empty when it cannot be read,
# which every caller treats as "not the endgame" — an unreadable clock must not
# be the thing that decides to take the window off somebody.
session_left_min() {
  python3 tools/weekly_usage.py --group session --resets-in 2>/dev/null \
    | awk 'NF{printf "%d", $1 * 60}'
}

# Is this window nearly over? $1 is a session_left_min reading.
in_endgame() {
  [ -n "$1" ] && [ "$1" -le "$SESSION_ENDGAME_MIN" ]
}

# How many puzzles the next wave should run at once.
#   $1 hours left   $2 the five-hour meter right now
# Inside the reserve a wave is a blunt instrument: four of them move the meter
# about ten points in one block that cannot be observed until it lands. So down
# there it goes one at a time, which keeps the most a returning person can lose
# to a wave already in flight at a couple of points.
wave_width() {
  local w
  w=$(python3 tools/prereset_plan.py --width "$1" 2>/dev/null || echo 1)
  # The exception is the end of the window, where one at a time is the wasteful
  # choice: a single run moves the meter about two points, so a reserve drained
  # that slowly is a reserve that expires half-full.
  if awk -v s="$2" -v r="$SESSION_RESERVE_PCT" 'BEGIN{exit !(s >= 100 - r)}' \
     && ! in_endgame "$(session_left_min)"; then w=1; fi
  echo "$w"
}

# Put the puzzles a lockout cut off back at the front of what is left to do.
# Without this the queue index walks straight past them: the job served the whole
# nap, came back to a window that would have run them, and spent it on the NEXT
# puzzles instead while the ones it had already half-paid for sat out the night.
#
# Once each. A puzzle failing for its own reasons — a clue the model cannot solve
# — must not be able to hold the queue open, and MAX_NAPS bounds the rest.
WAVE_FAILED_IDS=()
NAPPED=0
requeued=" "
requeue_failed() {
  local id back=()
  [ "$NAPPED" = 1 ] || return 0
  for id in ${WAVE_FAILED_IDS[@]+"${WAVE_FAILED_IDS[@]}"}; do
    case "$requeued" in *" $id "*) continue ;; esac
    requeued="$requeued$id "
    back+=("$id")
  done
  [ ${#back[@]} -eq 0 ] && return 0
  echo "  requeuing ${back[*]} — the window that refused them has turned over"
  queue=("${back[@]}" "${queue[@]:$at}")
  at=0
}

# Does the CLI still hold that conversation? A --resume naming a transcript that
# was never written fails on the spot, which would spend the puzzle's one retry
# on nothing.
session_exists() {
  [ -n "$(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" -maxdepth 2 \
            -name "$1.jsonl" 2>/dev/null | head -1)" ]
}

# Run one claude task against the repo. Returns non-zero if the run failed.
#
# Its output goes to a file named after the puzzle rather than to the log, because
# several of these run at once now and interleaved transcripts belong to nobody.
# The caller prints the tail of each one as it reaps it, in order.
#
# Every run is given a session id up front so that a retry can RESUME it rather
# than start over. A run the limit cut off had already read the puzzle, worked
# out the wordplay and written half the answers down; a fresh -p throws that
# thinking away and buys it a second time. Resuming replays the transcript and
# carries on from the reasoning already paid for.
run_claude() {
  local tag="$1" prompt="$2" log sid sidfile resume_at sess=()
  log="/tmp/ct-prereset-$1.txt"
  sidfile="/tmp/ct-prereset-$1.sid"
  resume_at="/tmp/ct-prereset-$1.resume"
  if [ "$DRY_RUN" = 1 ]; then
    echo "would spend one $MODEL run on $tag" >"$log"
    sleep 1
    return 0
  fi
  # WebSearch/WebFetch are here for the last rung only: when a clue will not come
  # apart, a solvers' blog is the difference between an annotation and a `null`,
  # and a `null` ships a clue with no teaching ladder. tools/annotate_prompt.md
  # bounds the use — stuck first, and the explanation written from scratch rather
  # than lifted, because the blog's prose teaches nobody in rungs.
  if [ -s "$resume_at" ] && [ -s "$sidfile" ] && session_exists "$(cat "$sidfile")"; then
    sess=(--resume "$(cat "$sidfile")")
    prompt=$(cat "$resume_at")
  else
    sid=$(uuidgen | tr '[:upper:]' '[:lower:]')
    echo "$sid" >"$sidfile"
    sess=(--session-id "$sid")
  fi
  rm -f "$resume_at"
  claude -p "$prompt" "${sess[@]}" \
    --model "$MODEL" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *),WebSearch,WebFetch" \
    --max-turns 80 >"$log" 2>&1
  local rc=$?
  # Running out of window is how this job is SUPPOSED to end, so a plain failure
  # stays quiet. A broken login is a different animal: it fails identically, at
  # the same point, every night, and it hid there for seven days (2026-07-31 to
  # 2026-08-06) precisely because it looked like the normal ending.
  if [ $rc -ne 0 ] && grep -qi "Failed to authenticate\|Not logged in" "$log"; then
    alert "pre-reset backfill cannot authenticate — the CLI needs a fresh /login. Nothing has been backfilled since this started."
  fi
  return $rc
}

# Run a wave of puzzles at once and commit the ones that survive validation.
#   $1   commit message prefix, e.g. "Annotate"
#   $2   the prompt, with every @ standing for the puzzle id
#   $3+  the ids
# Returns how many runs failed, and names them in WAVE_FAILED_IDS so the caller
# can put them back in the queue instead of losing them to a lockout that has
# since cleared. The claude runs are the only thing that happens
# in parallel: every git command below runs in this shell, one at a time, because
# a second process staging its own file mid-commit swallows it into ours.
run_wave() {
  local what="$1" tmpl="$2"; shift 2
  local ids=("$@") pids=() i failed=0
  WAVE_FAILED_IDS=()
  echo "--- wave of ${#ids[@]}: ${ids[*]} ---"
  local again=()
  for i in "${!ids[@]}"; do
    [ -s "/tmp/ct-prereset-${ids[$i]}.resume" ] && again+=("${ids[$i]}")
  done
  [ ${#again[@]} -gt 0 ] && echo "  picking up the cut-off conversations for: ${again[*]}"
  for i in "${!ids[@]}"; do
    run_claude "${ids[$i]}" "${tmpl//@/${ids[$i]}}" &
    pids+=($!)
  done
  for i in "${!ids[@]}"; do
    if wait "${pids[$i]}"; then
      tail -3 "/tmp/ct-prereset-${ids[$i]}.txt" | sed "s/^/  [${ids[$i]}] /"
      commit_puzzle "${ids[$i]}" "$what"
    else
      # A run cut off by a lockout usually leaves real work behind: some clues
      # annotated, the rest untouched, and that file still validates. Throwing
      # it away means paying for those clues again. Only a half-written one —
      # the run died mid-edit — is worth nothing and goes back.
      #
      # Either way it leaves a note for the retry, which resumes this same
      # conversation (see run_claude) — so the note only has to say what changed
      # under it while it was stopped, not restate the job.
      if [ -n "$(git status --porcelain -- "puzzles/${ids[$i]}.js")" ] &&
         python3 tools/validate_annotations.py "${ids[$i]}" >/dev/null 2>&1; then
        echo "  [${ids[$i]}] run failed — keeping what it finished, the file still validates"
        printf '%s\n' "You were cut off by a usage limit. The limit has since cleared and your edits to puzzles/${ids[$i]}.js are exactly as you left them. Pick up where you stopped, finish the task you were given, and run python3 tools/validate_annotations.py ${ids[$i]} until it passes. Do not commit." >"/tmp/ct-prereset-${ids[$i]}.resume"
      else
        echo "  [${ids[$i]}] run failed — discarding its changes"
        git checkout -- "puzzles/${ids[$i]}.js" 2>/dev/null
        printf '%s\n' "You were cut off by a usage limit, mid-edit, so puzzles/${ids[$i]}.js was rolled back to how it was before you started — check it before you assume anything about its contents. The limit has since cleared. You already did the solving, so write out what you had worked out rather than working it out again, finish the task you were given, and run python3 tools/validate_annotations.py ${ids[$i]} until it passes. Do not commit." >"/tmp/ct-prereset-${ids[$i]}.resume"
      fi
      WAVE_FAILED_IDS+=("${ids[$i]}")
      failed=$((failed + 1))
    fi
  done
  return $failed
}

# What a finished wave teaches, and whether to keep going.
#   $1 percent used before the wave  $2 hours it took  $3 how wide it was
#   $4 how many of its runs failed  $5 five-hour percent before the wave
# Returns non-zero when the caller should stop.
after_wave() {
  local before="$1" hours="$2" wide="$3" failed="$4" before_s="$5" now now_s climb climb_s
  local reserve_hold=0
  NAPPED=0
  now=$(python3 tools/weekly_usage.py 2>/dev/null || echo "$before")
  now_s=$(python3 tools/weekly_usage.py --group session 2>/dev/null || echo "$before_s")
  # awk -v, never string interpolation: an unset or empty number splices into the
  # program text and awk dies of a syntax error, which reads as a broken script
  # rather than as the missing reading it is.
  climb=$(awk -v a="$before" -v b="$now" 'BEGIN{print b - a}')
  climb_s=$(awk -v a="$before_s" -v b="$now_s" 'BEGIN{print b - a}')
  python3 tools/prereset_plan.py --observe "$climb" "$hours" "$wide" >/dev/null 2>&1
  # Both meters bill the same spend against different denominators, so every wave
  # where neither is pinned re-measures what a whole five-hour window is worth —
  # the number the start time is counted out of. The plan script throws away the
  # waves where one of them was pinned or had reset.
  python3 tools/prereset_plan.py --observe-yield "$climb" "$climb_s" >/dev/null 2>&1
  echo "  weekly ${before}% -> ${now}%, five-hour ${before_s}% -> ${now_s}% in ${hours}h at width ${wide}"
  # THE FIVE-HOUR METER IS SHARED WITH A PERSON. The weekly remainder is this
  # job's to spend and all of it is meant to go, but the windows it spends
  # through are the same ones Paul talks to the bridge on, and a window run to
  # 100% locks him out of his own account until it turns over.
  #
  # So the last SESSION_RESERVE_PCT of each window is his while he is there and
  # the job's while he is not, asked again after every wave. An empty room still
  # gets eaten to 100%; a conversation gets the window handed back and the job
  # naps until it turns over. The reserve is wide because the meter is only read
  # after a wave lands — see wave_width for the other half of that.
  #
  # Handing it back is a LOAN, not a gift. Quota left on a window when it turns
  # over is gone for nothing, so the nap below wakes for the window's last
  # SESSION_ENDGAME_MIN minutes and spends the reserve then regardless of who is
  # about — a lockout that late cannot outlast the window it is in.
  # This wave just re-measured the burn, so the endgame it implies is fresher
  # than the one the last wave computed. Sized at THIS wave's width, which is
  # the width the endgame will run at too.
  refresh_endgame "$wide"
  local left_min
  left_min=$(session_left_min)
  # Only when the wave came back clean: if the API already refused it, the window
  # is locked rather than lent, and calling that a reserve would size the nap to
  # a loan that is not going to be repaid until the window resets anyway.
  if [ "$failed" -eq 0 ] \
     && awk -v s="$now_s" -v r="$SESSION_RESERVE_PCT" 'BEGIN{exit !(s >= 100 - r)}' \
     && bridge_busy; then
    if in_endgame "$left_min"; then
      echo "  five-hour window at ${now_s}% with ${left_min}m left on it — spending the reserve anyway rather than letting it expire"
    else
      echo "  five-hour window at ${now_s}% and the bridge is in use — holding the last ${SESSION_RESERVE_PCT}% until this window's final ${SESSION_ENDGAME_MIN}m"
      reserve_hold=1
      failed=1
    fi
  fi
  [ "${failed:-1}" -eq 0 ] && return 0
  # A failed wave with room still on the weekly clock is almost always the
  # FIVE-hour limit, which clears by itself. Treating that as "the week is
  # over" is how a job built to spend the remainder leaves most of it behind.
  # Only the seven-day number gets to end the run.
  if awk -v n="$now" -v e="$EXHAUSTED" 'BEGIN{exit !(n >= e)}'; then
    echo "  weekly window is spent (${now}%) — stopping"
    return 1
  fi
  naps=$((naps + 1))
  if [ "$naps" -gt "$MAX_NAPS" ]; then
    echo "  $naps waits already and runs still fail — stopping rather than looping"
    return 1
  fi
  # A lockout we no longer need to wait out. Spending got us back on schedule, so
  # the remaining windows are enough and this one need not have been used at all.
  if ! still_behind; then stand_down; return 1; fi
  # Sleep until the five-hour window actually turns over, asked rather than
  # guessed. A nap shorter than the lockout spends a nap on a wave that was
  # always going to fail, and MAX_NAPS of those ends the job with most of the
  # last day, and most of the remainder, still unspent.
  #
  # Except when it was this job that stood down rather than the API that refused:
  # then the window is not locked, it is being lent out, and the wake-up belongs
  # at the start of the endgame so the loan comes back.
  local nap room why
  if [ "$reserve_hold" = 1 ] && [ -n "$left_min" ]; then
    nap=$(( (left_min - SESSION_ENDGAME_MIN) * 60 ))
    [ "$nap" -lt 60 ] && nap=60
    why="reserve handed back at ${now_s}% five-hour"
  else
    nap=$(awk -v h="$left_min" 'BEGIN{printf "%d", (h == "" ? 1 : h / 60) * 3600 + 120}')
    why="runs failed at ${now}% weekly — five-hour limit"
  fi
  room=$(( STOP_AT - $(date +%s) - 60 ))
  [ "$nap" -gt "$room" ] && nap="$room"
  if [ "$nap" -le 0 ]; then return 1; fi
  echo "  $why; waiting ${nap}s (nap $naps)"
  NAPPED=1
  sleep "$nap"
  return 0
}

# Commit whatever a task produced, but only if the tree still validates. A run
# that ran out of room mid-file leaves a half-written annotation behind, and
# committing that would publish a broken puzzle page at 06:15.
# puzzles/index.js and puzzles/index.json are generated from the puzzle files, so
# any two runs that both touched puzzles/ conflict here, and the conflict never
# carries information: the answer is always whatever a fresh reindex produces.
# One arrived the night of 2026-09-02, from an archive extend pushed to master
# while a wave was mid-flight, and it stopped the run with most of a window left.
#
# Only these two paths, and only when they are the ONLY thing unmerged. A
# conflict anywhere else is a real disagreement about authored text and must
# still stop the job — resolving it by regenerating would throw away a sibling's
# annotations without anyone finding out.
resolve_generated_conflict() {
  local unmerged
  unmerged=$(git diff --name-only --diff-filter=U)
  [ -z "$unmerged" ] && return 0
  if echo "$unmerged" | grep -qv '^puzzles/index\.\(js\|json\)$'; then
    return 1
  fi
  python3 tools/fetch_puzzle.py --reindex >/dev/null || return 1
  git add puzzles/index.js puzzles/index.json || return 1
  # The autostash git could not apply is still on the stack, holding the same
  # conflict. Left there it is applied again by the next rebase.
  case "$(git stash list | head -1)" in
    *autostash*) git stash drop -q ;;
  esac
  echo "  regenerated puzzles/index.* over a rebase conflict"
  return 0
}

commit_puzzle() {
  local num="$1" what="$2"   # num is a puzzle ID, e.g. cryptic-30089
  if [ "$DRY_RUN" = 1 ]; then echo "  would commit $what $num"; return 0; fi
  # This puzzle only. A whole-tree run would fail for a sibling in the same wave
  # that is still mid-write, and discard a good annotation to punish it.
  if ! python3 tools/validate_annotations.py "$num" >/tmp/ct-prereset-validate.txt 2>&1; then
    echo "VALIDATION FAILED after $what $num — discarding that puzzle's changes"
    tail -5 /tmp/ct-prereset-validate.txt
    git checkout -- "puzzles/$num.js" 2>/dev/null
    return 1
  fi
  # Solved-but-short is not a failure anywhere else in this pipeline: the nulled
  # clues just ship as "auto hints". Say so, once, per puzzle.
  loss=$(python3 tools/check_annotation_loss.py "$num" 2>&1) || \
    alert "pre-reset backfill left clues unsolved — $loss. They ship with no teaching ladder. Repeated across a night this means the model is not solving these puzzles."
  echo "$loss"
  if [ -n "$(git status --porcelain -- "puzzles/$num.js")" ]; then
    # One puzzle, on purpose: this job runs for hours and publishes as it goes,
    # so each finished puzzle reaches the site without waiting for the rest.
    # Named because it was just written, not as an allow-list — the sweep at the
    # end takes everything.
    git add "puzzles/$num.js"
    git commit -q -m "$what $num" -m "$ANNOTATE_TRAILER"
    # Nothing generated survives the rebase, because nothing generated is worth
    # carrying: the republish step rewrites every one of these files wholesale
    # from the puzzle sources, so the copy sitting in the tree right now is
    # already garbage. It used to ride across as part of the --autostash, and the
    # first time origin rebuilt the same pages the pop conflicted — 47 generated
    # files left unmerged, and an unmerged index fails every later `git commit`
    # AND every later autostash in the run ("Cannot save the current index
    # state"). Each wave after that spent a full four-puzzle annotation, could
    # commit none of it, and alerted; two nights' worth of that is what this
    # line prevents (2026-09-01).
    #
    # Exclusions, not a list of what to drop, for the reason the republish `add
    # -A` gives: a named list of generated paths is incomplete the day someone
    # adds a generated path. What is excluded is what a run actually authors —
    # a sibling wave's puzzle, still mid-write, and glossary edits under tools/.
    git checkout -q -- . ':(exclude)puzzles/*.js' ':(exclude)tools/'
    # --autostash still, for what is left: a plain rebase refuses outright with a
    # sibling's half-written puzzle unstaged ("cannot pull with rebase: You have
    # unstaged changes"). Every push in this job failed that way on the nights of
    # 2026-08-05 and 08-06, so the work stayed on the mini and the site went on
    # serving un-annotated puzzles that were annotated locally. HEAD is detached
    # in this worktree, so master is named on both sides of the push.
    git fetch -q origin master && git rebase -q --autostash origin/master &&
      git push -q origin HEAD:master || {
      # Folded into this puzzle's own commit rather than left staged: the tree
      # that gets pushed should be the tree the reindex describes, and a stray
      # staged index.* would ride along in whatever committed next.
      if resolve_generated_conflict; then git commit -q --amend --no-edit; fi
      git fetch -q origin master && git rebase -q --autostash origin/master &&
        git push -q origin HEAD:master ||
        alert "pre-reset backfill committed $what $num but could not push it — the site will not show it until someone pushes. See .prereset.log."
    }
    # An unmerged index is not this puzzle's problem, it is the rest of the
    # night's: every commit and every autostash from here on fails, so the job
    # would keep buying Opus annotations it cannot save and alert once per wave.
    # Stop while the alert still names one cause instead of five symptoms.
    if [ -n "$(git ls-files -u)" ]; then
      alert "pre-reset backfill wedged its worktree — a rebase left these unmerged: $(git diff --name-only --diff-filter=U | tr '\n' ' '). Nothing more can commit, so the run stopped rather than spend on work it cannot save. Resolve in $PWD, then push."
      exit 1
    fi
    echo "committed $what $num"
  else
    echo "$what $num produced no change"
  fi
  return 0
}

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not on PATH ($PATH) — nothing to do."
  exit 1
fi

python3 tools/fetch_puzzle.py --reindex >/dev/null

# Top the queue up from the archives before reading it. A window spent with
# nothing left to annotate wastes exactly as much as a window that stops early,
# and the papers publish four or five a day against a burn that clears far more,
# so the queue empties on its own. tools/extend_archive.py walks each paper
# backwards until the queue is deeper than the best week this job has had.
#
# Here rather than when the queue runs dry: the queue is read once below, and
# fetching mid-wave would race the reindex the running annotators read through.
#
# Never fatal. A paper being down is a smaller problem than not annotating.
if [ "$DRY_RUN" = 1 ]; then
  python3 tools/extend_archive.py --dry-run || true
else
  python3 tools/extend_archive.py ||
    echo "archive extend failed — running on what is already on disk"
fi

# --- 1. un-annotated puzzles, quiptics first ---------------------------------
echo "un-annotated backlog, newest first:"
todo=$(python3 - <<'EOF'
import json, sys
from datetime import datetime, timezone
idx = json.load(open("puzzles/index.json"))
todo = [p for p in idx["puzzles"] if not p["annotated"] and p.get("hasSolutions")]
# Newest first, by DATE and by date alone — one queue across every series.
#
# Not by number: each paper numbers from its own 1, so a number sort is a series
# sort wearing a disguise. It ran every Guardian cryptic (30,0xx), then every
# Independent (12,4xx), then every Indy Sunday (1,9xx), in that order, purely
# because of how big each paper's counter happens to be.
#
# Not by series tier either. Whichever series goes first, its whole archive goes
# before the other series' puzzle from yesterday, and the archive is always
# deeper than one window of quota — so the tail never runs and today is last.
todo.sort(key=lambda p: -p["date"])
# The order this job spends a whole window in is worth one readable line in the
# log. It ran in the wrong order for weeks behind a single line listing 166 ids.
# stderr, because stdout is the queue itself.
for p in todo[:5]:
    print(f"  {datetime.fromtimestamp(p['date'] / 1000, timezone.utc):%Y-%m-%d}  "
          f"{p['id']}", file=sys.stderr)
if len(todo) > 5:
    print(f"  ... and {len(todo) - 5} older", file=sys.stderr)
# IDs, not numbers: the file is puzzles/<id>.js and every consumer below names
# it directly, so nothing downstream has to resolve a number that two papers
# could one day share.
print(" ".join(p["id"] for p in todo))
EOF
)

# Not "Guardian crossword": since 2026-08-05 some of these are the
# Independent's. The puzzle file records its own series and publisher.
ANNOTATE_PROMPT="Annotate the crossword in puzzles/@.js in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Every clue needs a definitionFit, and every indicator needs an indicatorNotes entry saying why THAT word carries THAT instruction. Do not commit — the calling script commits."

# The prompt's Reference section, restated from the code that enforces it. Same
# reason daily_update.sh does it: the run should not have to grep for a rule.
python3 "$REPO/tools/build_annotate_prompt.py"

naps=0
queue=($todo)
at=0
while [ "$at" -lt "${#queue[@]}" ]; do
  if past_deadline; then echo "deadline reached — stopping"; break; fi
  if ! still_behind; then stand_down; break; fi
  # Re-asked every wave, not decided once: the remainder shrinks as we spend it,
  # the hours shrink faster, and something else on this machine may be spending
  # too. A width fixed at the top would be wrong by the second wave.
  hours_left=$(hours_between "$(date +%s)" "$STOP_AT")
  before=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
  before_s=$(python3 tools/weekly_usage.py --group session 2>/dev/null || echo 0)
  wide=$(wave_width "$hours_left" "$before_s")
  started=$(date +%s)
  run_wave "Annotate" "$ANNOTATE_PROMPT" "${queue[@]:$at:$wide}"
  failed=$?
  at=$((at + wide))
  after_wave "$before" "$(hours_between "$started" "$(date +%s)")" \
    "$wide" "$failed" "$before_s" || break
  requeue_failed
done

# --- 2. grandfathered-field backfill ------------------------------------------
# Additive only: these puzzles are already annotated and their hints are fine,
# they just predate a field. Anything that rewrites an existing hint here is a
# bug, not an improvement.
#
# The list of fields is read from tools/annotation_backlog.json, so a rule added
# next month is drained by this job without anyone editing it. Newest field
# first: it is the one the app has just started rendering, so it is the one a
# solver is most likely to hit an empty rung on.
backlog_fields=$(python3 -c 'import json;print(" ".join(k for k in json.load(open("tools/annotation_backlog.json")) if not k.startswith("_")))')

for field in $backlog_fields; do
  # Smallest backlog first: with an unknown amount of quota left, finishing four
  # puzzles beats getting most of the way through one.
  nums=$(python3 -c 'import json,sys
d=json.load(open("tools/annotation_backlog.json")).get(sys.argv[1],{})
print(" ".join(n for n,_ in sorted(d.items(), key=lambda kv: kv[1])))' "$field")
  echo "$field backlog: ${nums:-none}"
  case "$field" in
    definitionFit) what="ONE sentence saying why the answer means the definition; it renders last in the walkthrough" ;;
    indicatorNotes) what="an object keyed by the exact indicator string, ONE sentence each saying why THAT word carries THAT instruction — never the generic sentence about what the device does, and never a word of the answer" ;;
    *) what="the field as tools/annotate_prompt.md describes it" ;;
  esac
  prompt="In this repo, add the missing \`$field\` to every annotated clue in puzzles/@.js that lacks one. $field is $what. Read tools/annotate_prompt.md and STYLE.md for the voice, and read an existing puzzle that already has the field so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicators or pieces. Run python3 tools/validate_annotations.py @ until it passes. Do not commit — the calling script commits."
  queue=($nums)
  at=0
  while [ "$at" -lt "${#queue[@]}" ]; do
    if past_deadline; then echo "deadline reached — stopping"; break 2; fi
    if ! still_behind; then stand_down; break 2; fi
    hours_left=$(hours_between "$(date +%s)" "$STOP_AT")
    before=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
    before_s=$(python3 tools/weekly_usage.py --group session 2>/dev/null || echo 0)
    wide=$(wave_width "$hours_left" "$before_s")
    started=$(date +%s)
    run_wave "Backfill $field for" "$prompt" "${queue[@]:$at:$wide}"
    failed=$?
    at=$((at + wide))
    after_wave "$before" "$(hours_between "$started" "$(date +%s)")" \
      "$wide" "$failed" "$before_s" || break 2
    requeue_failed
  done
done

if [ "$DRY_RUN" = 1 ]; then
  echo "=== dry run — nothing spent, nothing built, nothing committed $(date '+%H:%M') ==="
  exit 0
fi

# Record what got drained. The allowance may only shrink — enforced in
# write_backlog, not merely intended — so every puzzle finished here is a puzzle
# that can never quietly lose the field again.
#
# NOT suppressed. This was `>/dev/null 2>&1 || true`, and under it the command
# had been raising TypeError on every run since puzzle ids stopped being bare
# numbers: the sort key was int(id). Months of drained puzzles were never
# recorded, and the one place that would have said so was pointed at /dev/null.
# A puzzle still uncommitted here is one a lockout cut off and the run never got
# back to. Keeping it was worth a retry; publishing it is not — the republish
# below stages the whole tree, and it would go out as a puzzle whose teaching
# ladder stops halfway down. Tomorrow's queue picks it up whole.
if [ -n "$(git status --porcelain -- puzzles/)" ]; then
  echo "dropping unfinished puzzles: $(git status --porcelain -- puzzles/ | awk '{print $2}' | tr '\n' ' ')"
  git checkout -- puzzles/
fi

python3 tools/validate_annotations.py --tighten ||
  alert "the pre-reset backfill could not record what it drained (validate_annotations.py --tighten failed), so tonight's finished puzzles can still silently lose their notes. See .prereset.log."

# --- 3. republish -------------------------------------------------------------
# Unconditionally, even if nothing was annotated: this is cheap, deterministic
# and idempotent, and running it always means a run that landed one puzzle and a
# run that landed none leave the tree in the same shape. The index, the static
# pages and the ?v= stamps have to move together, and the smoke test is the last
# word on whether the app still boots against what we just wrote.
python3 tools/fetch_puzzle.py --reindex
python3 tools/build_seo_pages.py
python3 tools/stamp_assets.py
if command -v node >/dev/null 2>&1; then
  smoke_log="$(mktemp -t cryptic-prereset-smoke)"
  node tools/smoke_test.js 2>&1 | tee "$smoke_log"
  smoke_rc=${PIPESTATUS[0]}
  # A WARNING in a log is not a warning to anyone: this printed failures for weeks
  # while the job committed the tree that caused them. Exit 2 is "no hints yet".
  if [ "$smoke_rc" -ne 0 ] && [ "$smoke_rc" -ne 2 ]; then
    alert "the app's smoke test is failing on the tree the pre-reset backfill is about to commit: $(grep -m3 '^FAIL' "$smoke_log" | tr '\n' ' ')"
  fi
  rm -f "$smoke_log"
fi
# The annotation payloads apply_annotations.py consumed, swept for the same
# reason daily_update.sh sweeps them: ignored is not the same as cleaned up.
rm -f "$REPO/tools/_ann_"*.json

if [ -n "$(git status --porcelain)" ]; then
  # Everything, for the reason daily_update.sh gives at its own `add -A`: this
  # is a worktree of the job's own, and a named list is both incomplete and
  # fatal — git add aborts on a path that matches nothing, staging none of it.
  git add -A
  git commit -q -m "$(printf 'Republish after pre-reset backfill\n\n%s' "$ANNOTATE_TRAILER")"
  left=$(git status --porcelain | cut -c4- | tr '\n' ' ')
  [ -n "$left" ] && alert "the pre-reset backfill committed, and left these behind in its own worktree: $left"
  # HEAD is detached here, so master is named on both sides — `pull --rebase`
  # has no upstream to read and `push origin HEAD` has no branch to write.
  git fetch -q origin master && git rebase -q --autostash origin/master &&
    git push -q origin HEAD:master || {
    if resolve_generated_conflict; then git commit -q --amend --no-edit; fi
    git fetch -q origin master && git rebase -q --autostash origin/master &&
      git push -q origin HEAD:master ||
      alert "pre-reset backfill could not push its republish commit — the built pages are committed locally only. See .prereset.log."
  }
fi

# Where the rollout got to. Nothing to flip by hand any more: the ratchet in
# tools/validate_annotations.py already requires these fields of every puzzle
# annotated since they were added, and the numbers below are only the historical
# remainder.
python3 tools/validate_annotations.py 2>&1 | grep -i "backlog" || true

echo "=== done $(date '+%H:%M') ==="
