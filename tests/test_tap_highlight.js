/* Paul 11-08: "When I tap a letter it gets light blue but when I backspace the
   light blue stays on that one." The light blue was a sticky :hover on touch.
   Tapping a box selects it (.cur), drawn like the grid cursor. */
"use strict";
const fs = require("fs");
const css = fs.readFileSync(__dirname + "/../style.css", "utf8");
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const hoverOnly = (sel) => new RegExp("@media \\(hover: hover\\) \\{ " + sel.replace(/[.]/g, "\\.") + ":hover \\{").test(css);
check(hoverOnly(".pat-box"), ".pat-box:hover only under (hover: hover)");
check(hoverOnly(".ana-tile"), ".ana-tile:hover only under (hover: hover)");
check(!/^\.(pat-box|ana-tile):hover/m.test(css), "no bare hover rule on tappable boxes");
check(/\.pat-box\.cur \{[^}]*background: var\(--cell-sel, var\(--sel\)\)/.test(css),
  "selected box is filled like the grid cursor, with a fallback: --cell-sel is only defined inside #grid");
process.exit(failures ? 1 : 0);
