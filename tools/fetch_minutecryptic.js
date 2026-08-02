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
//                  enumeration, date. NO answers and NO hints. Archived anyway
//                  because it is one cheap request and a year of real clues is
//                  worth having; do not expect hints to appear in it.
//
// WHAT LOGGING IN DOES AND DOES NOT BUY (checked 2026-08-02, so nobody has to
// go and find out again). We have an account, and it authenticates fine — the
// site is Supabase-backed, so a password grant plus the session cookie gets a
// real logged-in session. It gets us exactly one thing the anonymous path
// cannot see: the MINI clues, a second daily-ish series that the anon
// recommendation endpoint never returns. It does NOT get us the hint ladders,
// and the earlier note claiming it would was wrong. The daily hint texts and
// the back catalogue sit behind a PAID membership, not behind auth: the
// account's `subscriptions` row is empty, and every /archive/<date> page 307s
// straight to /subscribe — including dates this account has already solved.
// There is no hints table, RPC or REST route in their bundle either; the
// player fetches them on a surface we do not reach. So: log in for the minis,
// and treat course.json as the only hint corpus we actually have.
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
const SUPABASE = "https://pubnjtzifbxpdxwnmvhm.supabase.co";
const OUT = path.join(__dirname, "data", "minutecryptic");
const QUIET = process.argv.includes("--quiet");
const log = (...a) => { if (!QUIET) console.log(...a); };

// Set once we have logged in. Everything downstream just passes it through, so
// an anonymous run and a signed-in run are the same code path with a header
// missing — which is what keeps the fallback honest instead of theoretical.
let COOKIE = null;

async function get(url, asJson) {
  const r = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      accept: asJson ? "application/json" : "text/html",
      ...(COOKIE ? { cookie: COOKIE } : {}),
    },
  });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return asJson ? r.json() : r.text();
}

// --- signing in ------------------------------------------------------------

// The credential is NOT in this repo and must never be. It lives in the agent
// memory file, which is outside the public dotfiles checkout, and is read here
// at runtime the way tools/weekly_usage.py reads the OAuth token — never
// printed, never written to tools/data/. MC_EMAIL / MC_PASSWORD override it so
// the script stays usable somewhere the memory file doesn't exist.
const CRED_FILE = path.join(
  process.env.HOME, ".claude/projects/-Users-pt/memory/minutecryptic-account.md");

function credentials() {
  if (process.env.MC_EMAIL && process.env.MC_PASSWORD) {
    return { email: process.env.MC_EMAIL, password: process.env.MC_PASSWORD };
  }
  if (!fs.existsSync(CRED_FILE)) return null;
  const m = fs.readFileSync(CRED_FILE, "utf8").match(/`([^`\s]+@[^`\s]+)`\s*\/\s*`([^`]+)`/);
  return m ? { email: m[1], password: m[2] } : null;
}

// Their Supabase publishable key is embedded in the JS bundle, and the bundle
// filenames are content-hashed, so it is discovered rather than pinned — same
// reasoning as the chunk list below. A pinned key would outlive its rotation
// and we would find out months later.
async function anonKey() {
  const html = await get(SITE + "/");
  const chunks = [...new Set([...html.matchAll(/\/_next\/static\/chunks\/[A-Za-z0-9_./-]+\.js/g)]
    .map((m) => m[0]))];
  for (const c of chunks) {
    let src;
    try { src = await get(SITE + c); } catch { continue; }
    const k = src.match(/eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/);
    if (k) return k[0];
  }
  return null;
}

// Supabase's SSR client keeps the whole session in one base64 cookie, split
// into `.0`, `.1`, … past 3180 chars. Their Next middleware reads that cookie,
// not the Authorization header, so the bearer token alone is not enough for
// anything server-rendered.
async function signIn() {
  const cred = credentials();
  if (!cred) return "anonymous (no credential found)";
  const key = await anonKey();
  if (!key) return "anonymous (could not find their API key in the bundle)";
  const r = await fetch(`${SUPABASE}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: { apikey: key, "content-type": "application/json" },
    body: JSON.stringify(cred),
  });
  if (!r.ok) return `anonymous (login rejected: ${r.status})`;
  const session = await r.json();
  if (!session.access_token) return "anonymous (login returned no token)";
  const raw = "base64-" + Buffer.from(JSON.stringify(session)).toString("base64");
  const name = "sb-" + new URL(SUPABASE).hostname.split(".")[0] + "-auth-token";
  const parts = [];
  for (let i = 0; i < raw.length; i += 3180) parts.push(raw.slice(i, i + 3180));
  COOKIE = parts.length === 1
    ? `${name}=${parts[0]}`
    : parts.map((p, i) => `${name}.${i}=${p}`).join("; ");
  return "signed in";
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

const TZ = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

async function fetchDaily() {
  // Signed in there is a non-/anon twin of this route. It returns the same
  // fields plus solveStatus, which is a fact about our account rather than
  // about the clue — harmless, and worth keeping as a marker of which rows
  // came down authenticated.
  const route = COOKIE ? "recommended_today" : "recommended_today/anon";
  const d = await get(`${SITE}/api/v2/puzzles/${route}?tz=${encodeURIComponent(TZ())}`, true);
  return d.data || [];
}

// The list route, which only answers to a session. `type` is lower-case and
// the enum is narrow: "daily" and "mini" work, "DAILY"/"all"/"standard" all
// 400. limit caps somewhere under 50 — 20 is accepted, 50 is not.
//
// It paginates by cursor and we follow that, but do not expect depth: on a
// free account both series stop after seven days with hasNextPage false. The
// loop is here so this keeps working if the account is ever upgraded, not
// because it currently walks a back catalogue.
async function fetchSeries(type) {
  const rows = [];
  let cursor;
  for (let page = 0; page < 40; page++) {
    const q = new URLSearchParams({
      type, tz: TZ(), limit: "20", filter: "all", sort: "newest" });
    if (cursor) q.append("cursor", cursor);
    const d = await get(`${SITE}/api/v2/puzzles?${q}`, true);
    rows.push(...(d.data || []));
    if (!d.pageInfo || !d.pageInfo.hasNextPage) break;
    cursor = d.pageInfo.nextCursor;
  }
  return rows;
}

// Append-only, deduped by puzzle id. Their API returns a rolling window of
// several clues, so consecutive days overlap heavily; rewriting the file would
// be simpler but would lose anything they later unpublish.
//
// Keyed on type+id, not id: dailies are UUIDs but minis are small integers, so
// on id alone a mini would eventually collide with nothing and silently with
// each other across series.
const key = (r) => `${r.type || "DAILY"}:${r.id}`;

function appendDaily(rows) {
  const file = path.join(OUT, "daily.jsonl");
  const seen = new Set();
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, "utf8").split("\n")) {
      if (!line.trim()) continue;
      try { seen.add(key(JSON.parse(line))); } catch { /* skip a torn line */ }
    }
  }
  // Dedupe against the batch as well as the file. Signed in, today's clue comes
  // down twice — once from recommended_today and again from the type=daily
  // listing — so filtering only against what is already on disk appends it
  // twice on the very first authenticated run.
  const fresh = rows.filter((r) => r.id && !seen.has(key(r)) && seen.add(key(r)));
  if (fresh.length) {
    fs.appendFileSync(file, fresh.map((r) => JSON.stringify(r)).join("\n") + "\n");
  }
  // `seen` already absorbed the fresh rows during the filter above.
  return { fresh: fresh.length, total: seen.size };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  // Never fatal. A login that stops working should cost us the minis, not the
  // nightly capture — daily_update.sh calls this and a hard failure here would
  // take the whole run down over a reference corpus.
  let authMsg = "auth: skipped";
  try { authMsg = "auth: " + await signIn(); } catch (e) { authMsg = `auth: FAILED — ${e.message}`; }
  log("  " + authMsg);

  let dailyMsg = "daily: failed";
  try {
    const rows = await fetchDaily();
    // Minis only exist behind the session; ask for them, shrug if they 401.
    if (COOKIE) {
      for (const type of ["daily", "mini"]) {
        try { rows.push(...await fetchSeries(type)); } catch { /* series unavailable */ }
      }
    }
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

  if (QUIET) console.log(`minutecryptic — ${authMsg}; ${dailyMsg}; ${courseMsg}`);
})();
