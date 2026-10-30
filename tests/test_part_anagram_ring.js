/* Paul 10-30: "An anagram for part of a clue shouldn't show the wheel the
   building blocks. Only when it is all." A part-anagram's blocks rung carries
   no anagram wheel; a whole-answer anagram's still does.

     node tests/test_part_anagram_ring.js */
"use strict";
const src = require("fs").readFileSync(__dirname + "/../app.js", "utf8");
const slice = (from, to) => { const a = src.indexOf(from); return src.slice(a, src.indexOf(to, a)); };
// partAnagram and the helpers it reads, then ringHTML itself, run against
// stubs for the drawing so only the decision is under test.
const code = slice("  const bareLetters", "function ringFodder") + "function ringFodder" +
  slice("function ringFodder", "\n  }\n").slice("function ringFodder".length) + "\n  }\n" +
  slice("  const letterCount", "  // Fixed prose") +
  slice("  function ringKey", "  // The anagram the ring deals") +
  slice("  function ringHTML", "\n  }\n") + "\n  }\n";
const run = new Function("ringShelf_", "dealRing", "ringDraw",
  "let ringShelf = ringShelf_, ring;\n" + code + "\n return (ann) => ringHTML(ann);");
const html = run({}, (l) => l.map((_, i) => i), () => "<div class=\"anagram-ring\"></div>");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
check(html({ answer: "CHOMPED", assembly: { anagrams: [{ fodder: "COD HE", gives: "CHOED" }] } }) === "",
  "a part-anagram (CHO(MP)ED) shows no wheel");
check(html({ answer: "ORDNELSON", assembly: { anagrams: [{ fodder: "LONDONERS", gives: "ORDNELSON" }] } }).includes("anagram-ring"),
  "a whole-answer anagram still shows the wheel");
process.exit(failures ? 1 : 0);
