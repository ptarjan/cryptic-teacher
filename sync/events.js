/* The complete list of things this site is allowed to report about a session.

   Solving happens entirely in localStorage, so from the outside a visitor who
   read the first clue and left is indistinguishable from one who filled the
   whole grid. These names are the difference, and they are the only difference:
   each one is a fact about a puzzle session, and there is nothing in any of them
   about a person. See sync/worker.js for how one is stored and why two of them
   cannot be put back together into a visitor.

   Shared verbatim by the browser and the Worker so there is exactly one copy of
   the list. A second copy would drift, and the failure mode is silent in both
   directions: a name the page invents is dropped by the Worker, and a counter
   that reads zero looks exactly like a thing nobody does. tools/smoke_test.js
   holds the ends together.

   Loaded as a plain <script> in the page and imported by the Worker, hence the
   UMD wrapper — the same one sync/merge.js uses, for the same reason. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CTEvents = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  //   open      a puzzle was opened
  //   letter    the first letter typed into that puzzle this session
  //   hint1..6  the first time a clue's Nth hint rung was revealed this session
  //   check     a check button was used
  //   entry     the first entry completed correctly this session
  //   half      the grid passed halfway filled
  //   done      the puzzle was completed
  //
  // Written in the order a solve goes, because that is the order the report
  // reads them in: the question these answer is a funnel from "arrived" to
  // "finished", not a set of unrelated tallies (tools/usage_report.py).
  return Object.freeze([
    "open", "letter",
    "hint1", "hint2", "hint3", "hint4", "hint5", "hint6",
    "check", "entry", "half", "done"
  ]);
});
