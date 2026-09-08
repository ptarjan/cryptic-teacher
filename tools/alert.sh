# Shout, where a human will actually see it, when a scheduled run breaks.
#
# Source this, don't execute it:  . "$(dirname "$0")/alert.sh"
#
# Why it exists: on 2026-07-31 a /login rewrote the CLI's credentials under a
# different keychain key, and every scheduled annotation run from then until
# 2026-08-06 died on "Failed to authenticate". The script noticed, printed it,
# carried on with everything else, and committed cleanly — so the site kept
# updating, the log kept saying PASSED, and nobody found out for seven days.
# The lesson is not "check the log": nobody reads a log that is fine 99 days out
# of 100. A failure that only lands in a file nobody opens is a silent failure.
#
# So: anything that stops this job doing the one thing it exists to do gets a
# Discord message. It reuses the bridge bot's token rather than owning a
# credential of its own, and every failure mode here is a no-op — an alert that
# can't be sent must never take the run down with it.
#
# Identical alerts are sent once per ALERT_REPEAT_HOURS. The pre-reset job polls
# hourly, so on 2026-08-07 one lapsed access token produced the same paragraph
# four times in a row, and a channel that cries wolf on the hour trains its one
# reader to scroll past it — which is the silent failure again, wearing the
# opposite mask. The log still records every occurrence; only Discord is spared.
ALERT_CHANNEL="${ALERT_CHANNEL:-1530815234019692624}"   # #cryptic-crosswords
# The bridge checkout sits beside this one, so derive it from this file rather
# than from $HOME: the two are the same directory on the Mac and different
# directories in a container, and only one of those spellings finds the file.
ALERT_ENV_FILE="${ALERT_ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." \
  && pwd)/household/.env}"
ALERT_STATE_DIR="${ALERT_STATE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." \
  && pwd)/.alert-state}"
ALERT_REPEAT_HOURS="${ALERT_REPEAT_HOURS:-12}"

# Everything in a run's output that means something broke, sent here as the
# lines themselves.
#
# The alerts below are hand-placed: each one guards a failure somebody already
# thought of. This one guards the rest. A scheduled job's real failure mode is
# not the branch with an alert on it — it is the traceback, the "usage:" from a
# tool called with the wrong argument, the CLI that isn't on PATH. Those printed
# and the run carried on, and on 2026-08-28 the log had been carrying
# `apply_solution.py: error: argument number: invalid int value: 'everyman-4166'`
# for days: a whole model solve, paid for and thrown away, every single night.
#
# Matched on a short allowlist rather than the word "error", because a hint
# warning that happens to contain the word must not cry wolf — this channel has
# one reader and an alert they learn to scroll past is worse than none.
#
# The lines travel IN the message. "See the log" is not a report: the reader is
# on a phone and the log is on the mini.
alert_run_failures() {
  local log="$1" hits
  [ -r "$log" ] || return 0
  hits=$(grep -nE '^Traceback \(most recent call last\)|^[a-zA-Z_./]+\.py: error:|^usage: [a-zA-Z_]+\.py|: command not found|^VALIDATION FAILED|rejected — nothing written|^refresh .* failed:|^ERROR: |^[a-zA-Z_./]+: line [0-9]+: ' "$log" |
    cut -c1-200 | head -8)
  [ -n "$hits" ] || return 0
  alert "the run printed $(printf '%s\n' "$hits" | wc -l | tr -d ' ') failure line(s) nobody had written an alert for:"$'\n'"\`\`\`"$'\n'"$hits"$'\n'"\`\`\`"
}

alert() {
  echo "ALERT: $*"
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
  if "$wake_sh" -c "$ALERT_CHANNEL" "⚠️ cryptic-teacher: $*"; then
    touch "$stamp" 2>/dev/null || true
  else
    echo "the alert could not be sent: wake.sh failed"
  fi
}
