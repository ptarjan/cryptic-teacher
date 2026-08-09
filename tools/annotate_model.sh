#!/bin/bash
# Sourced, not run. Turns $ANNOTATE_MODEL into the Co-Authored-By trailer the
# annotation commits carry, so the model is named in exactly one place.
#
# Why this file exists: the trailer was hardcoded as "Claude Fable 5" in three
# scripts. When the nightly job silently moved to Opus on 2026-07-30 (an
# inherited default, see daily_update.sh), a week of commits kept crediting
# Fable, and the git history — the one record of which model wrote which
# annotation — was quietly wrong. Deriving it means the wrong version cannot be
# written.
#
# Unknown models get a generic trailer rather than a guess. A missing version
# number is honest; a wrong one is the bug this file was written to kill.

case "${ANNOTATE_MODEL:-}" in
  fable|claude-fable-5)   ANNOTATE_TRAILER="Claude Fable 5" ;;
  opus|claude-opus-5)     ANNOTATE_TRAILER="Claude Opus 5" ;;
  sonnet|claude-sonnet-5) ANNOTATE_TRAILER="Claude Sonnet 5" ;;
  haiku|claude-haiku-*)   ANNOTATE_TRAILER="Claude Haiku 4.5" ;;
  *)                      ANNOTATE_TRAILER="Claude (${ANNOTATE_MODEL:-unset})" ;;
esac
ANNOTATE_TRAILER="Co-Authored-By: ${ANNOTATE_TRAILER} <noreply@anthropic.com>"
