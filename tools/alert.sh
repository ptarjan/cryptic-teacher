# Shout, where a human will actually see it, when a scheduled run breaks.
#
# Source this, don't execute it:  . "$(dirname "$0")/alert.sh"
#
# Why it exists: a run that fails one step, prints it, and carries on with
# everything else still commits cleanly, so the site keeps updating and the log
# keeps saying PASSED. Nobody reads a log that is fine 99 days out of 100; a
# failure that only lands in a file nobody opens is a silent failure.
#
# So: anything that stops this job doing the one thing it exists to do wakes the
# room. It reuses the bridge bot's token rather than owning a
# credential of its own, and every failure mode here is a no-op — an alert that
# can't be sent must never take the run down with it.
#
# Identical alerts are sent once per ALERT_REPEAT_HOURS. The pre-reset job fires
# hourly, so one lapsed access token would otherwise post the same paragraph
# every hour, and a channel that cries wolf on the hour trains its one reader to
# scroll past it — which is the silent failure again, wearing the opposite mask.
# The log still records every occurrence; only the channel is spared.
#
# The room is a NAME, never an id. An id names one front, so a hard-coded one
# keeps posting to that service after the bridge moves, and nothing about a
# delivered message says it went to the room nobody reads. wake.sh resolves the
# name against both fronts and DEFAULT_FRONT decides, so this follows the bridge
# wherever it goes.
ALERT_CHANNEL="${ALERT_CHANNEL:-cryptic-crosswords}"
# The bridge checkout sits beside the MAIN checkout of this repo, so derive it
# from the repository rather than from this file or from $HOME. Not $HOME: it is
# the checkout's parent on the Mac and a different directory in the container.
# Not this file's own grandparent either — sourced from a nightly worktree two
# levels under CT_WORKTREE_ROOT, that names a household beside the worktrees,
# where there is no wake.sh. A worktree's git-common-dir is the main checkout's
# .git from either place.
ALERT_ENV_FILE="${ALERT_ENV_FILE:-$(dirname "$(dirname "$(git \
  -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute \
  --git-common-dir 2>/dev/null || echo "$(dirname "${BASH_SOURCE[0]}")/../.git")")")/household/.env}"
ALERT_STATE_DIR="${ALERT_STATE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." \
  && pwd)/.alert-state}"
ALERT_REPEAT_HOURS="${ALERT_REPEAT_HOURS:-12}"

# Everything in a run's output that means something broke, sent here as the
# lines themselves.
#
# The alerts below are hand-placed: each one guards a failure somebody already
# thought of. This one guards the rest. A scheduled job's real failure mode is
# not the branch with an alert on it — it is the traceback, the "usage:" from a
# tool called with the wrong argument, the CLI that isn't on PATH. Those print
# and the run carries on, so one wrong argument can throw away a paid-for model
# solve every night without any hand-placed alert firing.
#
# Matched on a short allowlist rather than the word "error", because a hint
# warning that happens to contain the word must not cry wolf — this channel has
# one reader and an alert they learn to scroll past is worse than none.
#
# The lines travel IN the message. "See the log" is not a report: the reader is
# on a phone and the log is on the mini.
#
# A line a hand-placed alert already carried is not unclaimed. An alert that
# quotes the traceback explaining it puts that quote on stdout, into this same
# log; without the filter one failure would arrive twice, once explained and
# once as a bare `Traceback` line. Filtered on the text an alert really sent, so
# a new alert that quotes its own cause is covered without editing this list.
alert_run_failures() {
  local log="$1" hits claimed line exc
  [ -r "$log" ] || return 0
  claimed="$(mktemp "${TMPDIR:-/tmp}/cryptic-claimed.XXXXXX")"
  printf '%s' "${ALERT_CLAIMED:-}" > "$claimed"
  hits=$(grep -nE '^Traceback \(most recent call last\)|^[a-zA-Z_./]+\.py: error:|^usage: [a-zA-Z_]+\.py|: command not found|^VALIDATION FAILED|rejected — nothing written|^refresh .* failed:|^ERROR: |^[a-zA-Z_./]+: line [0-9]+: ' "$log" |
    while IFS= read -r line; do
      grep -qxF -- "${line#*:}" "$claimed" && continue
      # An alert quotes a traceback's tail, so its header is claimed by the
      # exception line that ends it: the first unindented line after it.
      if [ "${line#*:}" = "Traceback (most recent call last):" ]; then
        exc=$(tail -n +"$((${line%%:*} + 1))" "$log" | grep -m1 -v '^[[:space:]]' | cut -c1-200)
        [ -n "$exc" ] && grep -qxF -- "$exc" "$claimed" && continue
      fi
      printf '%s\n' "$line"
    done | cut -c1-200 | head -8)
  rm -f "$claimed"
  [ -n "$hits" ] || return 0
  alert "the run printed $(printf '%s\n' "$hits" | wc -l | tr -d ' ') failure line(s) nobody had written an alert for:"$'\n'"\`\`\`"$'\n'"$hits"$'\n'"\`\`\`"
}

# A line a path prints on its way to its own alert: printed, and claimed as
# that alert's, so alert_run_failures does not report it a second time.
echo_alerted() {
  printf '%s\n' "$*"
  ALERT_CLAIMED="${ALERT_CLAIMED:-}$*"$'\n'
}

alert() {
  echo "ALERT: $*"
  ALERT_CLAIMED="${ALERT_CLAIMED:-}$*"$'\n'
  local stamp
  stamp="$ALERT_STATE_DIR/$(printf '%s' "$*" | shasum | cut -c1-16)"
  mkdir -p "$ALERT_STATE_DIR" 2>/dev/null || true
  if [ -f "$stamp" ] &&
     [ -z "$(find "$stamp" -mmin "+$((ALERT_REPEAT_HOURS * 60))" 2>/dev/null)" ]
  then
    echo "(identical alert sent within ${ALERT_REPEAT_HOURS}h — not repeating)"
    return 0
  fi
  # The bridge drops every bot-authored message, so an alert posted straight to
  # Discord lands in the channel and wakes nobody. wake.sh is the bridge's own
  # door for exactly this: it owns the marker, the token and the channel check,
  # and it is tested against the config that reads them. This file asks it to
  # speak rather than keeping a second copy of any of that.
  local wake_sh
  wake_sh="$(dirname "$ALERT_ENV_FILE")/tools/wake.sh"
  if [ ! -x "$wake_sh" ]; then
    echo "the alert could not be sent: no wake.sh at $wake_sh"
    return 0
  fi
  # Stamped only once it is out, so a failed send is retried by the next run
  # rather than suppressed as a duplicate of a message nobody ever saw.
  # The icon is the triage signal in a channel of these, so it is not always a
  # warning: a blind solve that graded clean is a result, and dressing a result
  # as a problem is what costs the ⚠️ its meaning. A caller says so for one
  # message — ALERT_ICON="✅" alert "..." — and it falls back to a warning on
  # every call that does not, so nothing goes quiet by forgetting.
  if "$wake_sh" -c "$ALERT_CHANNEL" "${ALERT_ICON:-⚠️} cryptic-teacher: $*"; then
    touch "$stamp" 2>/dev/null || true
  else
    echo "the alert could not be sent: wake.sh failed"
  fi
}
