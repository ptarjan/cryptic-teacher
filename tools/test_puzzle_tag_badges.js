/* The tags tools/puzzle_tags.py puts in the index reach the solver.

     node tools/test_puzzle_tag_badges.js

   1. The puzzle title badges a tagged puzzle with its label, and the mirror:
      an untagged puzzle's title has no feature badge.
   2. The picker's feature menu offers only tags some puzzle carries, and
      choosing one lists exactly the puzzles that have it, a stronger tag that
      implies it included (a double pangram is a pangram). */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const TAGGED = "independent-9740";   // a quintuple pangram
const PLAIN = "cryptic-30066";

{
  const d = boot({ query: "?p=" + TAGGED });
  const title = d.registry["puzzle-title"].innerHTML;
  check(/class="badge feature"[^>]*>quintuple pangram</.test(title),
    "a tagged puzzle's title badges its tag: " + title.slice(0, 200));
}
{
  const d = boot({ query: "?p=" + PLAIN });
  check(!/badge feature/.test(d.registry["puzzle-title"].innerHTML),
    "(mirror) an untagged puzzle's title has no feature badge");
}
{
  const d = boot({ query: "?p=" + PLAIN });
  const reg = d.registry;
  const index = global.window.CRYPTIC_INDEX;
  reg["btn-picker"].onclick();
  const menu = [...reg["picker-tag"].innerHTML.matchAll(/value="([^"]*)"/g)].map((m) => m[1]);
  const info = index.tags;
  const has = (p, t) => (p.tags || []).some((k) => k === t || (info[k] && info[k].implies === t));
  check(menu[0] === "" && menu.length > 1, "the feature menu is 'any' then the tags: " + menu.join("|"));
  check(menu.slice(1).every((t) => index.puzzles.some((p) => has(p, t))),
    "every tag offered matches some listed puzzle");
  check(!menu.includes("octuple-pangram") || index.puzzles.some((p) => has(p, "octuple-pangram")),
    "(mirror) a tag no puzzle carries is not offered");
  const matched = () => reg["picker-list"].children.length
    + Number((/(\d+) more match/.exec(reg["picker-more"].innerHTML) || [0, 0])[1]);
  ["pangram", "special-rules"].filter((t) => menu.includes(t)).forEach((t) => {
    reg["picker-tag"].value = t;
    reg["picker-tag"].listeners.change[0]();
    const want = index.puzzles.filter((p) => has(p, t)).length;
    check(matched() === want, `choosing "${t}" lists its ${want} puzzles: ${matched()}`);
    check(reg["picker-note"].innerHTML.length > 0, `choosing "${t}" says what it means`);
  });
  const doubles = index.puzzles.filter((p) => (p.tags || []).includes("double-pangram")).length;
  const singles = index.puzzles.filter((p) => (p.tags || []).includes("pangram")).length;
  reg["picker-tag"].value = "pangram";
  reg["picker-tag"].listeners.change[0]();
  check(matched() === singles + doubles + index.puzzles.filter((p) => (p.tags || [])
    .some((k) => k !== "double-pangram" && info[k] && info[k].implies === "pangram")).length,
    "the pangram filter includes the doubles and up");
}
process.exit(failures ? 1 : 0);
