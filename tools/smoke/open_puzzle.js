// The puzzle that booted: title, heading, meta, grid, the cells it draws.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { assert, canonicalLink, document, htmlEsc, openId, registry } = T;
// Which puzzle boots is NOT pinned here on purpose: the nightly job adds one
// every day, and a test that only ever exercises a frozen fixture stops
// covering the puzzles people actually land on. Everything below therefore
// derives its expectations (entry lengths, letters to type) from whichever
// puzzle opened, rather than hard-coding one puzzle's answers. Set CT_TEST_QUERY=?p=30067 to pin one while debugging.
const openTitle = registry["puzzle-title"].innerHTML;
const openPuz = (global.window.CRYPTIC_PUZZLES || {})[openId];
assert(openPuz, "the opened puzzle's data is loaded: " + openId);
// The title carries the puzzle's own name, so the check is that it says that
// name. A number is ONE series' way of naming itself and must not be read as
// the puzzle's identity: a date-keyed paper (the Canberra Times) names itself by
// date and carries no "No", so a /No [\d,]+/ scrape resolves to no puzzle at all
// the night one is the newest. Escaped the way app.js escapes it, so the two cannot drift.
// The heading shows a date once (app.js headingParts): a name that carries its own
// full date loses it from the title text and the date follows in a muted span.
const bareName = openPuz.name.replace(/,?\s*(?:(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat(?:ur)?|Sun)[a-z]*,?\s+)?\d{1,2} [A-Z][a-z]+ \d{4}/, "").replace(/\s+/g, " ").trim();
const escName = htmlEsc(bareName);
assert(bareName.length > 0, "the puzzle's name is more than its date: " + openPuz.name);
assert(openTitle.includes(escName),
  `the title names the opened puzzle: want ${escName}, got ${openTitle}`);
assert(bareName === openPuz.name || openTitle.includes('class="muted"'),
  `a name stripped of its date leaves the date beside it: ${openTitle}`);
// A ?p= URL hands its indexing credit to the static write-up, not to the
// homepage: canonicalling to the site root credits the front page for every
// link to a specific puzzle. With no ?p the
// URL really is the homepage, and so is the canonical.
{
  const home = "https://cryptic.paultarjan.com/";
  const asked = new URLSearchParams(global.location.search).get("p");
  const meta = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === asked);
  const want = (meta && meta.hasSolutions) ? `${home}puzzles/${meta.id}/` : home;
  assert(canonicalLink.href === want,
    `canonical should be ${want}, got ${canonicalLink.href}`);
  // Google overrides that canonical and indexes ?p= in the write-up's place, so
  // a ?p= URL with a write-up (or for an unlisted puzzle) is noindex too.
  const robots = document.querySelector('meta[name="robots"]');
  const noindex = !!(meta && (meta.unlisted || meta.hasSolutions));
  assert(!!(robots && robots.content === "noindex") === noindex,
    `?p=${asked} should ${noindex ? "" : "not "}be noindex, got ${robots && robots.content}`);
}

// The badge marks the exception, not the norm: an annotated puzzle's title
// carries no badge at all (see docs/APP.md, "Badge the exception"). So the title
// must agree with the index rather than always saying something.
{
  const idx = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === openId);
  // "hints via <blog>" is the same exception said the other way round: we
  // have not annotated it, and a blog's write-up is what the hints come from.
  const title = registry["puzzle-title"].innerHTML;
  const badged = title.includes("answers only") || title.includes("hints via ");
  assert(idx && badged === !idx.annotated,
    "title badge disagrees with the index for " + openId + ": badged=" + badged);
}

// No difficulty band without having solved the puzzle first.
// tools/difficulty.py enforces this by requiring its wordplay component, which
// only exists once a puzzle is annotated — but that is one `if` guarding a rule
// that matters, and the failure is silent and plausible-looking: the Guardian's
// beginner Quiptic came out rated BRUTAL on the shape of its grid. So check the
// shipped index rather than trusting the generator, and check every puzzle
// rather than the one the app happened to open.
{
  const graded = (global.CRYPTIC_INDEX.puzzles || [])
    .filter((p) => p.difficulty && !p.annotated)
    .map((p) => p.number);
  assert(graded.length === 0,
    "unsolved puzzles carry a difficulty band: " + graded.join(", ")
    + " — grade from the annotations or leave it unknown");
}

// The walkthrough below is the full-hints path: it climbs the hint ladder and
// reveals letters, and neither exists on a puzzle with no annotations or no
// published solutions (Saturday prize crosswords arrive bare). Both of those
// degraded paths get their own section further down. Landing here on one is a
// pinning mistake, so say it once rather than failing eight assertions and
// crashing on a button the app was right not to render.
const openMeta = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === openId) || {};
if (!openMeta.annotated || !openMeta.hasSolutions) {
  console.error(`SKIPPED: No ${openId} is ${openMeta.annotated ? "unsolved" : "un-annotated"}, ` +
    "and the main walkthrough needs a full-hints puzzle. Unset CT_TEST_QUERY, or pin an annotated one.");
  process.exit(2);
}

const cellCount = openPuz.dimensions.cols * openPuz.dimensions.rows;
assert(registry["grid"].children.length === cellCount,
  `grid has ${cellCount} cells, got ` + registry["grid"].children.length);
const lightCells = registry["grid"].children.filter((c) => !c.classList.contains("block"));
// A share of the grid, not a count. A British blocked grid is between a half
// and three quarters light whatever its size, and a fixed floor only ever
// describes one size: the Metro's 13x13 has 109 lights, which is 64% and
// perfectly normal.
assert(lightCells.length > cellCount * 0.5,
  `light cells present: ${lightCells.length} of ${cellCount}`);
// One list item per entry, in each direction — not "more than ten". A floor is
// a 15x15 figure in disguise: the Metro's 13x13 has exactly 10 across clues.
// Counting against the puzzle's
// own entries is also the stronger check, because it catches a list that
// renders one clue too many as well as one that renders none.
for (const dir of ["across", "down"]) {
  const want = openPuz.entries.filter((e) => e.direction === dir).length;
  assert(registry["clues-" + dir].children.length === want,
    `${dir} clues rendered: ${registry["clues-" + dir].children.length} of ${want}`);
}
assert(registry["hint-clue"].innerHTML.length > 10, "hint panel shows a clue");

Object.assign(T, { lightCells, openPuz });
