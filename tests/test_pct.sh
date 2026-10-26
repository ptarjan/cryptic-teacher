#!/bin/bash
# Does the site's progress percent floor, and only say 100% when it is?
#
#     bash tests/test_pct.sh
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }
got() { PYTHONPATH=tools python3 -c "import build_seo_pages as b; print(b.pct($1, $2))"; }
same "245 of 246 is not 100%" "$(got 245 246)" "99%"
same "1403 of 1403 is 100%" "$(got 1403 1403)" "100%"
same "1 of 1000 is &lt;1%" "$(got 1 1000)" "&lt;1%"
same "0 of 5 is 0%" "$(got 0 5)" "0%"
same "1 of 3 floors to 33%" "$(got 1 3)" "33%"
exit $((fails > 0))
