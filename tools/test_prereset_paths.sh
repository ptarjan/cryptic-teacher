#!/bin/bash
# The two paths the pre-reset burn resolves at runtime, checked by resolving
# them — not by matching the text of the line that builds them.
#
# Both were wrong from 2026-09-06 (the container cutover) to 2026-09-08 and
# neither said so. BRIDGE_DIR named a directory that has never existed, so the
# occupancy check read every empty room as busy and held 25% of every five-hour
# window back for nobody. alert.sh looked for the bridge beside the worktrees
# instead of beside the checkout, so the one alert that would have reported it
# printed "no wake.sh" into the log nobody opens.
#
# Run standalone or from tools/smoke_test.js.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# BRIDGE_DIR follows the CLI's config dir, which is not under $HOME in the
# container. Both are set to decoys here so a spelling that reaches for the
# wrong one lands somewhere this test can name.
mkdir -p "$tmp/config/projects/-Users-pt" "$tmp/home/.claude/projects/-Users-pt"
got="$(HOME="$tmp/home" CLAUDE_CONFIG_DIR="$tmp/config" BRIDGE_DIR= bash -c '
  unset BRIDGE_DIR
  eval "$(grep "^BRIDGE_DIR=" "$1")"
  echo "$BRIDGE_DIR"' _ "$ROOT/tools/prereset_backfill.sh")"
check "BRIDGE_DIR follows CLAUDE_CONFIG_DIR, not \$HOME" \
  "$got" "$tmp/config/projects/-Users-pt"

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
