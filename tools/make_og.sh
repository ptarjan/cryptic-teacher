#!/bin/bash
# Render the 1200x630 social card (og.png) from tools/og_card.html.
# Headless Chrome rather than hand-drawn pixels, because the card needs real type.
# Re-run after editing tools/og_card.html.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Rebuild the clue block from a published puzzle before screenshotting. It also
# checks that the answer really is hidden where the card underlines it, so the
# card can't go back to being a picture that quietly asserts something false.
python3 "$REPO/tools/make_og_card.py"
"$CHROME" --headless --disable-gpu --hide-scrollbars \
  --screenshot="$REPO/og.png" --window-size=1200,630 \
  "file://$REPO/tools/og_card.html" 2>/dev/null
echo "wrote og.png"
