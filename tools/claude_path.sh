# Put the `claude` CLI on PATH, wherever this machine keeps it. Source it.
#
# One home for a fact that both timed jobs need and that is different on every
# machine they run on: a Mac installs the CLI under ~/.local/bin or
# ~/.claude/local, the bridge container symlinks it into /usr/local/bin, and on
# a host where nothing installed it separately the only copy is the one the
# agent SDK ships inside its own wheel. A job that cannot find it does not
# fail — it skips annotation and reports the machine as logged out — so this
# looks in all of them before giving up.
export PATH="$HOME/.local/bin:$HOME/.claude/local:$HOME/.local/node/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
if ! command -v claude >/dev/null 2>&1; then
  # Located through the package rather than by path, which is pinned to a
  # Python version this script has no business knowing.
  bundled=$(python3 -c 'import claude_agent_sdk, os; print(os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled"))' 2>/dev/null)
  if [ -n "$bundled" ] && [ -x "$bundled/claude" ]; then
    export PATH="$bundled:$PATH"
  fi
fi
