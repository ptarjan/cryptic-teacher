#!/bin/bash
# The bridge path the pre-reset burn's alerts resolve at runtime, checked by
# resolving it — not by matching the text of the line that builds it. alert.sh
# must find the bridge beside the checkout, not beside the worktrees, or every
# alert prints "no wake.sh" into a log nobody opens.
#
# Run standalone or from tools/smoke_test.js.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# alert.sh finds the bridge checkout from a nightly worktree, which sits two
# levels below its own root and nowhere near the checkout it was cloned from.
git init -q "$tmp/github/repo"
git -C "$tmp/github/repo" -c user.email=t@t -c user.name=t commit -qm init --allow-empty
git -C "$tmp/github/repo" worktree add -q -b wt "$tmp/worktrees/nightly" 2>/dev/null
mkdir -p "$tmp/worktrees/nightly/tools" "$tmp/github/household/tools"
cp "$ROOT/tools/alert.sh" "$tmp/worktrees/nightly/tools/alert.sh"
: > "$tmp/github/household/.env"
printf '#!/bin/sh\n' > "$tmp/github/household/tools/wake.sh"
chmod +x "$tmp/github/household/tools/wake.sh"
got="$(bash -c 'unset ALERT_ENV_FILE; . "$1"; echo "$ALERT_ENV_FILE"' \
  _ "$tmp/worktrees/nightly/tools/alert.sh")"
check "alert.sh finds the bridge beside the checkout, not beside the worktrees" \
  "$got" "$tmp/github/household/.env"

[ "$fails" = 0 ] && echo "PRERESET PATHS PASSED" || echo "$fails check(s) failed"
exit $((fails > 0))
