#!/bin/bash
# The catch-all in alert.sh reports failure lines nobody wrote an alert for.
# Checked by running it — an alert is sent, and the log it leaves behind is fed
# to the catch-all exactly as the exit trap feeds it.
#
# An alert that quotes a traceback puts that traceback on stdout too, so the
# catch-all must not find it in the log and send it a second time as
# unexplained: two messages for one failure, the second claiming nobody
# thought of it.
#
# Run standalone or from tools/smoke_test.js.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/household/tools" "$tmp/state"
: > "$tmp/household/.env"
printf '#!/bin/sh\nexit 0\n' > "$tmp/household/tools/wake.sh"
chmod +x "$tmp/household/tools/wake.sh"

# One run, wired the way daily_update.sh wires itself: everything printed goes
# to a log, and the exit trap hands that same log back to the catch-all.
run() {  # run <alert-text-or-empty> <line-the-run-printed-or-empty>
  rm -rf "$tmp/state"; mkdir -p "$tmp/state"
  local log="$tmp/run.log"; : > "$log"
  ALERT_ENV_FILE="$tmp/household/.env" ALERT_STATE_DIR="$tmp/state" \
  bash -c '
    . "$1"
    exec > >(tee -a "$2") 2>&1
    [ -n "$3" ] && alert "$3"
    [ -n "$4" ] && printf "%s\n" "$4"
    sleep 1
    alert_run_failures "$2"
    sleep 1
  ' _ "$ROOT/tools/alert.sh" "$log" "$1" "$2" >/dev/null 2>&1
  grep -c "nobody had written an alert for" "$log" | tr -d ' '
}

traceback="Traceback (most recent call last):"

check "a traceback an alert already quoted is not reported again" \
  "$(run "the bad-hint queue could not be read. This is why:

$traceback" "")" "0"

check "a traceback no alert claimed is still reported" \
  "$(run "" "$traceback")" "1"

check "a claimed traceback does not silence an unrelated failure" \
  "$(run "the bad-hint queue could not be read. This is why:

$traceback" "VALIDATION FAILED")" "1"

# Alerts quote `tail -12` of a tool's output, which drops the header of a
# long traceback; the exception line that ends it still claims it.
frames='  File "tools/andlit_azed.py", line 98, in get
    return r.geturl(), r.read()
http.client.IncompleteRead: IncompleteRead(786216 bytes read, 167601 more expected)'
check "a traceback whose tail an alert quoted is not reported again" \
  "$(run "tools/andlit_azed.py failed:
$frames" "$traceback
$frames")" "0"
check "a traceback ending in an unquoted exception is still reported" \
  "$(run "tools/andlit_azed.py failed:
$frames" "$traceback
  File \"x.py\", line 1, in f
KeyError: 4923")" "1"

# A path that prints its own failure line before alerting claims it by
# printing it with echo_alerted, so the catch-all does not report it again.
claimed_line() {  # claimed_line <line> -> catch-all reports for that run
  rm -rf "$tmp/state"; mkdir -p "$tmp/state"
  local log="$tmp/run.log"; : > "$log"
  ALERT_ENV_FILE="$tmp/household/.env" ALERT_STATE_DIR="$tmp/state" \
  bash -c '
    . "$1"
    exec > >(tee -a "$2") 2>&1
    echo_alerted "$3"
    alert "annotation validation failed"
    sleep 1
    alert_run_failures "$2"
    sleep 1
  ' _ "$ROOT/tools/alert.sh" "$log" "$1" >/dev/null 2>&1
  grep -c "nobody had written an alert for" "$log" | tr -d ' '
}

check "a failure line printed with echo_alerted is not reported again" \
  "$(claimed_line "VALIDATION FAILED on telegraph-31315 — reverting those puzzle files")" "0"
check "the same line printed with echo is still reported" \
  "$(run "annotation validation failed" "VALIDATION FAILED on telegraph-31315 — reverting those puzzle files")" "1"

# --- the icon says which kind of message this is ---
# An alert is a warning (⚠️) unless the caller sets ALERT_ICON for that one
# message, and it must fall back to the warning the moment it does not —
# a result that quietly stops looking like a problem is the worse failure.
icon() {  # icon <ALERT_ICON-or-empty> -> the leading token wake.sh was handed
  rm -rf "$tmp/state"; mkdir -p "$tmp/state"
  printf '#!/bin/sh\nprintf "%%s\\n" "$3" > "%s/sent"\n' "$tmp" \
    > "$tmp/household/tools/wake.sh"
  chmod +x "$tmp/household/tools/wake.sh"
  ALERT_ENV_FILE="$tmp/household/.env" ALERT_STATE_DIR="$tmp/state" ALERT_ICON="$1" \
    bash -c '. "$1"; alert "something happened"' _ "$ROOT/tools/alert.sh" >/dev/null 2>&1
  cut -d" " -f1 < "$tmp/sent"
}

check "an alert with nothing said about it is a warning" "$(icon "")" "⚠️"
check "and a caller may send a result as a result" "$(icon "✅")" "✅"

# --- the room is a name, so it follows the bridge between fronts ---
# ALERT_CHANNEL is a room name, not a channel id: an id names one service and
# cannot be re-pointed; a name is resolved by wake.sh against both fronts, and
# DEFAULT_FRONT decides.
room() {  # -> the channel wake.sh was handed
  rm -rf "$tmp/state"; mkdir -p "$tmp/state"
  printf '#!/bin/sh\nprintf "%%s\\n" "$2" > "%s/sent"\n' "$tmp" \
    > "$tmp/household/tools/wake.sh"
  chmod +x "$tmp/household/tools/wake.sh"
  ALERT_ENV_FILE="$tmp/household/.env" ALERT_STATE_DIR="$tmp/state" \
    bash -c '. "$1"; alert "something happened"' _ "$ROOT/tools/alert.sh" >/dev/null 2>&1
  cat "$tmp/sent"
}

r="$(room)"
check "the default room is a name, not one service's id" \
  "$(case "$r" in ''|*[!0-9]*) echo name ;; *) echo "an id: $r" ;; esac)" "name"
check "and it is this repo's room" "$r" "cryptic-crosswords"

[ "$fails" = 0 ] && echo "ALERT CLAIMED PASSED" || echo "$fails check(s) failed"
exit $((fails > 0))
