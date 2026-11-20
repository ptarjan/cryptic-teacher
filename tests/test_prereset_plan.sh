#!/usr/bin/env bash
# The burn's planner: width from the meter, the bridge's measured spend and the
# machine's free memory and cores, the manual resets counted off
# usage-history.csv and the windows planned for them, the owner's predicted nights
# (tools/awake.py: the profile from synthetic message times, a fill moved out of
# his night, the overnight cap), and the queue order. Their cases live in the
# scripts themselves (--self-test).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/awake.py --self-test
python3 tools/prereset_plan.py --self-test
