#!/bin/bash
# The catch-all in alert.sh reports failure lines nobody wrote an alert for.
# Checked by running it — an alert is sent, and the log it leaves behind is fed
# to the catch-all exactly as the exit trap feeds it.
#
# On 2026-09-08 a KV read broke and the run alerted properly, quoting the
# traceback that explained it. That quote goes to stdout with the alert, so the
# catch-all found the same traceback in the same log and sent it a second time
# as unexplained. Two messages, one failure, and the second one says nobody
# thought of this — which is the alert nobody reads, arriving by another route.
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

# --- the icon says which kind of message this is ---
# Everything alert.sh sends used to wear a ⚠️, so a blind solve that graded 28/28
# arrived as a warning (Paul's channel, 2026-09-12). A caller may say otherwise
# for one message, and must fall back to the warning the moment it does not —
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

[ "$fails" = 0 ] && echo "ALERT CLAIMED PASSED" || echo "$fails check(s) failed"
exit $((fails > 0))
