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
ALERT_ENV_FILE="${ALERT_ENV_FILE:-$HOME/github/discord-claude/.env}"
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
  [ -r "$ALERT_ENV_FILE" ] || return 0
  local stamp
  stamp="$ALERT_STATE_DIR/$(printf '%s' "$*" | shasum | cut -c1-16)"
  mkdir -p "$ALERT_STATE_DIR" 2>/dev/null || true
  if [ -f "$stamp" ] &&
     [ -z "$(find "$stamp" -mmin "+$((ALERT_REPEAT_HOURS * 60))" 2>/dev/null)" ]
  then
    echo "(identical alert sent within ${ALERT_REPEAT_HOURS}h — not repeating)"
    return 0
  fi
  touch "$stamp" 2>/dev/null || true
  local token
  token=$(grep -m1 '^DISCORD_BOT_TOKEN=' "$ALERT_ENV_FILE" | cut -d= -f2-)
  [ -n "$token" ] || return 0
  local wake body
  # The wake marker is not decoration: the bridge drops every bot-authored
  # message, and this one is posted with the bridge's own token, so unmarked it
  # lands in the channel and wakes nothing (which is how these alerts sat unread
  # on 2026-08-07). Self-authored + that exact marker + an allowlisted channel
  # is what makes it a turn — see cfg.is_wake in discord-claude.
  #
  # So it is READ from that config, never spelled here. A marker copied by hand
  # is one edit away from a message nothing reads and nothing reports, which is
  # the same silent failure this whole file exists to prevent. If it can't be
  # read the alert still goes out: a human seeing it beats nobody seeing it.
  wake=$(cd "$(dirname "$ALERT_ENV_FILE")" 2>/dev/null &&
         python3 -c 'import config; print(config.WAKE_PREFIX)' 2>/dev/null)
  [ -n "$wake" ] || wake="(unmarked — could not read the bridge's wake prefix)"
  body=$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1][:1900]}))' \
         "$wake ⚠️ cryptic-teacher: $*") || return 0
  curl -s -m 15 -o /dev/null \
    -H "Authorization: Bot $token" -H "Content-Type: application/json" \
    -d "$body" \
    "https://discord.com/api/v10/channels/$ALERT_CHANNEL/messages" || true
}
