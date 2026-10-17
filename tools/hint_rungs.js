// The hint rungs the app shows, as JSON, for tools that compare them with something.
//
//   node tools/hint_rungs.js cryptic-30078 cryptic-30079 > /tmp/rungs.json
//
// -> {"<puzzle>": {"<number>-<direction>": [["type", "text"], ["definition", "text"], ...]}}
//
// Booted over fake_dom.js and read off the real hint panel, answer masking and
// all, because ladderSteps() in app.js is the only place the wording lives: a
// Python copy of it (compare_mc.ladder_steps) drifted, and did not mask the
// answer, so hintcheck flagged rungs the learner never sees. The rung keys come
// from the LABELS table in app.js itself, read off its source.
"use strict";
const fs = require("fs");
const path = require("path");
const { boot, ROOT } = require("./fake_dom.js");

const ids = process.argv.slice(2);
if (!ids.length) { console.error("usage: node tools/hint_rungs.js <puzzle-id>..."); process.exit(2); }

const src = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const table = src.match(/const LABELS = \{([^}]*)\}/)[1];
const keyOf = {};
for (const m of table.matchAll(/(\w+): "([^"]+)"/g)) keyOf[m[2]] = m[1];

const text = (html) => String(html)
  .replace(/<[^>]*>/g, " ")
  .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
  .replace(/&gt;/g, ">").replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"')
  .replace(/\s+/g, " ").trim();

// Only the asked-for puzzles are indexed: a full rebuild is 57k puzzles.
require("./reindex.js").scoped(ids);

const out = {};
for (const id of ids) {
  const dom = boot({ query: "?p=" + id });
  const puz = (global.window.CRYPTIC_PUZZLES || {})[id];
  if (!puz) { console.error("no such puzzle: " + id); dom.stop(); continue; }
  out[id] = {};
  for (const e of puz.entries) {
    if (!e.annotation) continue;
    const row = dom.registry["clue-" + e.number + "-" + e.direction];
    if (!row || !row.listeners.click) continue;
    row.listeners.click[0]();
    for (let guard = 0; guard < 40; guard++) {
      const btn = dom.registry["hint-next"].children[0];
      if (!btn || !btn.onclick || btn.disabled) break;
      if (!/^\d+ · |^Next building block · /.test(btn.textContent || "")) break;
      btn.onclick();
      // A rung that asks for a guess first: take "Just tell me".
      if (dom.registry["hint-body"].innerHTML.includes('class="hint-step guess"')) dom.registry["guess-tell"].onclick();
    }
    const steps = [];
    for (const chunk of String(dom.registry["hint-body"].innerHTML).split('<div class="hint-step').slice(1)) {
      const m = chunk.match(/class="step-label">\d+ · ([^<]*)<\/span>([\s\S]*)/);
      if (m && keyOf[m[1]]) steps.push([keyOf[m[1]], text(m[2])]);
    }
    out[id][e.number + "-" + e.direction] = steps;
  }
  dom.stop();
}
process.stdout.write(JSON.stringify(out) + "\n");
