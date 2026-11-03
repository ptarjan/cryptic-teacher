"""The app's source as one string: the seven app-*.js scripts joined back into
the single IIFE they were split from. Mirror of tools/app_src.js; see there."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["app-core.js", "app-view.js", "app-play.js", "app-teach.js",
         "app-paint.js", "app-picker.js", "app-boot.js"]
HEAD = ('/* Cryptic Teacher — vanilla JS, no build step. Works from file:// and any static host. */\n'
        '(function () {\n  "use strict";\n')
TAIL = "})();\n"


def read(root=ROOT):
    root = Path(root)
    return HEAD + "".join(
        (root / f).read_text(encoding="utf-8").split("\n", 1)[1] for f in FILES) + TAIL
