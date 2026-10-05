/* The corpus-wide half of tools/smoke_test.js's shape() checks.

   Each nightly slice writes {slice, of, shapes: {name: seenBool}} to a file in
   one directory (CT_SHAPES_OUT). A slice holds a sixteenth of the corpus, so
   "the corpus holds an example of X" is true when SOME slice saw X. This
   asserts every one of the `of` slices reported, and every shape any of them
   registered was seen by at least one.

   Usage: node tools/check_shapes.js <dir of slice json files> */
"use strict";
const fs = require("fs");
const path = require("path");

const dir = process.argv[2];
const reports = fs.readdirSync(dir).filter((f) => f.endsWith(".json"))
  .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf8")));
const fail = [];
const of = reports.length ? reports[0].of : 0;
const got = new Set(reports.map((r) => r.slice));
if (!of || reports.some((r) => r.of !== of)) fail.push("slice reports disagree on how many slices there are");
for (let i = 0; i < of; i++) if (!got.has(i)) fail.push(`slice ${i}/${of} never reported its shapes`);
const union = {};
for (const r of reports) for (const [k, v] of Object.entries(r.shapes)) union[k] = union[k] || v;
for (const [k, v] of Object.entries(union)) if (!v) fail.push(`no slice found ${k}`);
if (!Object.keys(union).length) fail.push("no shapes were registered at all");
if (fail.length) {
  console.error("FAIL: the corpus no longer holds a shape the smoke test checks:\n  " + fail.join("\n  "));
  process.exit(1);
}
console.log(`ok: ${Object.keys(union).length} corpus shapes, each seen by at least one of ${of} slices`);
