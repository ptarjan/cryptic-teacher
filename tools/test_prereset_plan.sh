#!/usr/bin/env bash
# The burn's planner: width from the meter, the bridge's measured spend and the
# machine's free memory and cores, and the queue order. Its cases live in the
# script itself (--self-test).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/prereset_plan.py --self-test
