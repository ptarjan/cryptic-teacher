#!/usr/bin/env bash
# No tracked Python file carries a `# noqa` lint suppression: fix the code
# the rule flags instead (narrow the except, hoist the import, use `with`).
# A broad catch or a lazy import that is right says why in a plain comment.
set -euo pipefail
cd "$(dirname "$0")/.."
hits=$(git grep -n -E '#[[:space:]]*noqa\b' -- '*.py' || true)
if [ -n "$hits" ]; then
  printf '%s\n' "$hits"
  echo "test_no_noqa: fix what each noqa above suppresses, then delete it"
  exit 1
fi
echo "test_no_noqa: all passed"
