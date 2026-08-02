#!/usr/bin/env node
// Capture Minute Cryptic's hint writing, so ours can be judged against a
// working example instead of against my own taste.
//
// Minute Cryptic is one clue a day with a progressive hint ladder — the same
// shape as our six rungs — and their hints are the best-written ones on the
// internet. Two different things come down from the site, and only one of them
// is the good stuff:
//
//   course.json  — 55 fully worked examples baked into the public JS bundle:
//                  clue, answer, and an ORDERED list of hints, each tagged with
//                  a type (indicators / fodder / definition / …) and the exact
//                  character span it highlights in the clue. This is a teaching
//                  corpus, and it is what "our hints should be like theirs"
//                  actually means in data.
//   daily.jsonl  — the day's clues from their public API. Clue text, setter,
//                  enumeration, date. NO answers and NO hints: the daily hint
//                  texts are served per-user behind auth and are not reachable
//                  from here. Archived anyway because it is one cheap request
//                  and a year of real clues is worth having; do not expect
//                  hints to appear in it.
//
// The bundle filenames carry content hashes and change whenever they deploy, so
// the chunk list is discovered from the live HTML every run rather than pinned.
// A pinned URL would 404 silently and we would notice in about six months.
//
// Output goes to tools/data/minutecryptic/, which is GITIGNORED: this is
// somebody else's copyrighted teaching material with no declared licence, kept
// locally as reference the way tools/data/grading/ keeps the georgeho corpus.
// It must never be committed, republished, or copied into a puzzle file — read
// it to learn how a hint should read, then write our own.
//
// Usage: node tools/fetch_minutecryptic.js [--quiet]

const fs = require("fs");
const path = require("path");

const SITE = "https://www.minutecryptic.com";
const OUT = path.join(__dirname, "data", "minutecryptic");
const QUIET = process.argv.includes("--quiet");
const log = (...a) => { if (!QUIET) console.log(...a); };

async function get(url, asJson) {
  const r = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      accept: asJson ? "application/json" : "text/html",
    },
  });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return asJson ? r.json() : r.text();
}

// --- the worked examples ---------------------------------------------------

// Every entry is an object literal starting `{puzzleName:` sitting in a map
// keyed by lesson slug (`wordplay_containers_2`). Brace-match it out and
// evaluate it: it is pure data — strings, numbers, arrays — no calls, no JSX.
// Anything that doesn't evaluate to a clue-with-hints is skipped rather than
// thrown on, because a bundle can hold half-shaped objects we don't care about.
function extractExamples(src, into) {
  let i = 0;
  while ((i = src.indexOf("{puzzleName:", i)) >= 0) {
    let depth = 0, j = i;
    for (; j < src.length; j++) {
      const c = src[j];
      if (c === "{") depth++;
      else if (c === "}" && --depth === 0) { j++; break; }
    }
    try {
      const o = new Function("return " + src.slice(i, j))();
      if (o && o.clue && Array.isArray(o.hints) && o.hints.length) {
        const m = src.slice(Math.max(0, i - 60), i).match(/([A-Za-z0-9_]+):\s*$/);
        into[m ? m[1] : o.puzzleName] = o;
      }
    } catch { /* not a data literal; the next match may be */ }
    i = j;
  }
}

async function fetchCourse() {
  // Two entry points: the home page and the play route pull different chunks,
  // and the lessons are split across both.
  const pages = await Promise.all([get(SITE + "/"), get(SITE + "/puzzles")]);
  const chunks = [...new Set(pages.flatMap((h) =>
    [...h.matchAll(/\/_next\/static\/chunks\/[A-Za-z0-9_./-]+\.js/g)].map((m) => m[0])))];
  log(`  ${chunks.length} bundle chunks`);
  const examples = {};
  for (const c of chunks) {
    let src;
    try { src = await get(SITE + c); } catch { continue; }
    // cheap filter — only a couple of chunks carry lesson data
    if (src.includes("{puzzleName:")) extractExamples(src, examples);
  }
  return examples;
}

// --- today's clues ---------------------------------------------------------

async function fetchDaily() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const d = await get(
    `${SITE}/api/v2/puzzles/recommended_today/anon?tz=${encodeURIComponent(tz)}`, true);
  return d.data || [];
}

// Append-only, deduped by puzzle id. Their API returns a rolling window of
// several clues, so consecutive days overlap heavily; rewriting the file would
// be simpler but would lose anything they later unpublish.
function appendDaily(rows) {
  const file = path.join(OUT, "daily.jsonl");
  const seen = new Set();
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, "utf8").split("\n")) {
      if (!line.trim()) continue;
      try { seen.add(JSON.parse(line).id); } catch { /* skip a torn line */ }
    }
  }
  const fresh = rows.filter((r) => r.id && !seen.has(r.id));
  if (fresh.length) {
    fs.appendFileSync(file, fresh.map((r) => JSON.stringify(r)).join("\n") + "\n");
  }
  return { fresh: fresh.length, total: seen.size + fresh.length };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  let dailyMsg = "daily: failed";
  try {
    const rows = await fetchDaily();
    const { fresh, total } = appendDaily(rows);
    dailyMsg = `daily: +${fresh} new of ${rows.length} offered (${total} archived)`;
  } catch (e) {
    dailyMsg = `daily: FAILED — ${e.message}`;
  }
  log("  " + dailyMsg);

  let courseMsg = "course: failed";
  try {
    const examples = await fetchCourse();
    const n = Object.keys(examples).length;
    const file = path.join(OUT, "course.json");
    const before = fs.existsSync(file)
      ? Object.keys(JSON.parse(fs.readFileSync(file, "utf8")).examples || {}).length : 0;
    if (n === 0) {
      // Their bundle shape changed, or the fetch was blocked. Do NOT overwrite a
      // good corpus with an empty one — that is how a silent scraper failure
      // turns into lost data rather than a visible error.
      courseMsg = `course: found 0 examples — KEEPING the ${before} already saved (bundle shape changed?)`;
    } else {
      fs.writeFileSync(file, JSON.stringify(
        { source: SITE, fetched: new Date().toISOString().slice(0, 10), examples }, null, 1));
      courseMsg = `course: ${n} worked examples (was ${before})`;
    }
  } catch (e) {
    courseMsg = `course: FAILED — ${e.message}`;
  }
  log("  " + courseMsg);

  if (QUIET) console.log(`minutecryptic — ${dailyMsg}; ${courseMsg}`);
})();
