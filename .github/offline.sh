#!/usr/bin/env bash
# The `shell:` of every workflow step that runs repo code: the step's script
# runs in a network namespace with loopback and nothing else.
#
#     shell: bash .github/offline.sh {0}
#
# A test that reaches the internet then fails at once with "Network is
# unreachable" instead of passing or timing out on the weather of a remote
# host. Fix such a test by stubbing the fetch, never by giving the network
# back. 127.0.0.1 still works, so a test may serve its own fixture over HTTP.
#
# The namespace needs root to create and to bring lo up, so the script is run
# back as the runner user with its environment and PATH (sudo resets PATH, and
# setup-python and setup-node put their tools on it).
set -euo pipefail

if [ "${1:-}" = --inside ]; then
  shift
  if python3 -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)" 2>/dev/null; then
    echo "offline.sh: example.com is reachable, so the network was not cut" >&2
    exit 1
  fi
  exec bash --noprofile --norc -eo pipefail "$@"
fi

script=$(realpath "$1")
exec sudo -E unshare --net -- sh -c '
  ip link set lo up
  exec setpriv --reuid="$1" --regid="$2" --init-groups env PATH="$3" bash "$4" --inside "$5"
' sh "$(id -u)" "$(id -g)" "$PATH" "$(realpath "$0")" "$script"
