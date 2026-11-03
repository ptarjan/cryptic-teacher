// Fake-DOM smoke test: boots the app in Node with a minimal DOM stub and exercises
// grid typing, the hint ladder, check/reveal, picker, degradation and persistence.
// Usage: node tools/smoke_test.js
//
// The checks live in tools/smoke/, one file per feature, run in the order below
// in this one process (they share state: the booted app, the corpus sample, the
// assertion count). The lines are plain require() calls so that
// tests/test_ci_cache_deps.js can follow them. harness.js is the shared ground; sync_optin.js arms the
// timer that reports and exits, so the sections after it run in the same tick.
"use strict";
require("./smoke/harness");
require("./smoke/static_checks");
require("./smoke/corpus");
require("./smoke/app_source");
require("./smoke/open_puzzle");
require("./smoke/chrome");
require("./smoke/newcomer");
require("./smoke/ladder_typing");
require("./smoke/picker");
require("./smoke/degraded_open");
require("./smoke/blog_hints");
require("./smoke/links");
require("./smoke/reset_scroll");
require("./smoke/sync_merge");
require("./smoke/clue_text");
require("./smoke/sync_optin");
require("./smoke/finish_events");
require("./smoke/blocks_rung");
require("./smoke/search_menus");
require("./smoke/type_rung");
require("./smoke/rung_rules");
require("./smoke/typing_reports");
require("./smoke/stats");
require("./smoke/linked_answers");
require("./smoke/puzzle_format");
