# Sourced first by shell entry points that a nice-19 burn starts in a session of
# its own: see yield_cpu.py, the one implementation. A no-op below nice 19.
python3 "$(dirname "${BASH_SOURCE[0]}")/yield_cpu.py" 2>/dev/null || true
