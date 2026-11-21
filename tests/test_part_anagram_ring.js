/* Paul 10-30: "An anagram for part of a clue shouldn't show the wheel the
   building blocks. Only when it is all." A part-anagram's blocks rung carries
   no anagram wheel; a whole-answer anagram's still does.

     node tests/test_part_anagram_ring.js */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
const slice = (from, to) => { const a = src.indexOf(from); return src.slice(a, src.indexOf(to, a)); };
// partAnagram and the helpers wheelFodder reads, run against the real source.
const code = slice("  const bareLetters", "  // The answer's words, one ring each") +
  slice("  const letterCount", "  // Fixed prose") +
  slice("  function wheelFodder", "\n  }\n") + "\n  }\n";
const fodder = new Function(code + "\n return wheelFodder;")();

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
check(fodder({ type: ["anagram"], answer: "CHOMPED", assembly: { anagrams: [{ fodder: "COD HE", gives: "CHOED" }] } }) === "",
  "a part-anagram (CHO(MP)ED) deals nothing");
check(fodder({ type: ["anagram"], answer: "ORDNELSON", assembly: { anagrams: [{ fodder: "LONDONERS", gives: "ORDNELSON" }] } }) === "LONDONERS",
  "a whole-answer anagram deals its fodder");
check(fodder({ type: ["anagram"], answer: "TAR", assembly: { anagrams: [{ fodder: "RAT", gives: "TAR" }] } }) === "",
  "three letters deal nothing");
check(fodder({ type: ["charade"], answer: "ORDNELSON", assembly: { anagrams: [{ fodder: "LONDONERS", gives: "ORDNELSON" }] } }) === "",
  "a clue not typed anagram deals nothing");
process.exit(failures ? 1 : 0);
