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
  local body
  body=$(python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1][:1900]}))' \
         "⚠️ cryptic-teacher: $*") || return 0
  curl -s -m 15 -o /dev/null \
    -H "Authorization: Bot $token" -H "Content-Type: application/json" \
    -d "$body" \
    "https://discord.com/api/v10/channels/$ALERT_CHANNEL/messages" || true
}
