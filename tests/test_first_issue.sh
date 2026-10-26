#!/usr/bin/env bash
# Every series with a first issue has a row in tools/first_issue.py's SOURCES,
# and a missing No 1 says where it looked. Its cases live in the script itself
# (--self-test).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/first_issue.py --self-test
