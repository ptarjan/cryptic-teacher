// The app is seven classic scripts that share the page's global scope (no build
// step, no modules). They were one 10,000-line IIFE; this is the one place that
// knows the pieces, and read() puts them back together as that single IIFE
// source, byte for byte, for everything that greps or runs the app's code
// (tools/smoke_test.js, tools/fake_dom.js, the tests/ that read its source).
//
//   - Each file's first line is a `"use strict";` wrapper, dropped here.
//   - HEAD and TAIL are the IIFE's opening and closing lines.
//   - Order is the load order; index.html preloads the same list.
// Mirror: tools/app_src.py.
const fs = require("fs");
const path = require("path");

const FILES = ["app-core.js", "app-view.js", "app-play.js", "app-teach.js",
               "app-paint.js", "app-picker.js", "app-boot.js"];
const HEAD = '/* Cryptic Teacher — vanilla JS, no build step. Works from file:// and any static host. */\n' +
             '(function () {\n  "use strict";\n';
const TAIL = "})();\n";

function read(root) {
  return HEAD + FILES.map((f) =>
    fs.readFileSync(path.join(root, f), "utf8").replace(/^[^\n]*\n/, "")).join("") + TAIL;
}

module.exports = { FILES, read };
