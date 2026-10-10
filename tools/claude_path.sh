# Put the `claude` CLI on PATH, wherever this machine keeps it. Source it.
#
# One home for a fact that every timed job needs and that is different on every
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

# A job started from a bridge session (track-job, a hand start) inherits the
# bridge's own claude variables, and its runs would pass for bridge turns:
# tagged entrypoint sdk-py, which the usage tally skips as the bridge's, and
# carrying the bridge's session id. Every run starts from none of them.
# CLAUDE_CONFIG_DIR stays: it is where the job's login lives.
unset CLAUDECODE CLAUDE_PID CLAUDE_EFFORT CLAUDE_MODEL CLAUDE_AGENT_SDK_VERSION \
  CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID CLAUDE_CODE_CHILD_SESSION \
  CLAUDE_CODE_MESSAGING_SOCKET CLAUDE_CODE_MESSAGING_TOKEN CLAUDE_CODE_SHELL_PREFIX \
  CLAUDE_CODE_SESSION_ATTENDED CLAUDE_CODE_EXECPATH CLAUDE_CODE_TMPDIR \
  CLAUDE_CODE_STREAM_CLOSE_TIMEOUT CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION
