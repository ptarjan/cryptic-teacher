/* Cryptic Teacher sync — a Cloudflare Worker in front of one KV namespace.

   There is no login here on purpose. The sync code *is* the account: eight
   characters the browser generates, which you type on the other machine. There
   is no email to store, no password to reset, no session to expire, and nothing
   in KV but crossword letters — so the worst case for a guessed code is that a
   stranger sees how far along someone is on an Everyman.

   The Worker merges rather than overwrites (see merge.js). That matters even
   with one user: without it, an iPad that had been offline would push a stale
   save over the laptop's afternoon and silently eat it. With it, a push can
   only ever add. */
import CTMerge from "./merge.js";
import CTEvents from "./events.js";
import CTNotify from "./notify.js";
import { send, GONE } from "./webpush.js";

// No 0/O/1/I/L — this gets read off one screen and typed into another, by hand.
const CODE_RE = /^[2-9A-HJ-KMNP-TV-Z]{8}$/;
const MAX_BODY = 512 * 1024;   // ~100 puzzles of letters is a few tens of KB
const MAX_PUZZLES = 2000;
const TTL = 60 * 60 * 24 * 365; // a code untouched for a year is abandoned
const EVENT_TTL = 60 * 60 * 24 * 90; // a quarter, so this month has a month to compare against
const MAX_EVENT = 32;           // the longest name on the list, with room to spare
const MAX_REPORT = 2 * 1024;    // a sentence about a hint, with room for a long clue id
const MAX_NOTE = 400;           // what fits in the one-line box on the page
const REPORT_TTL = 60 * 60 * 24 * 365;
// What a solver thought of a clue or a puzzle. A year, because the aggregate is
// the point — a page that says "nobody has rated this" about a puzzle eleven
// people rated last spring is worse than saying nothing.
const VOTE_TTL = 60 * 60 * 24 * 365;
const MAX_VOTE = 64;
// c:<puzzle>:<clue> or p:<puzzle>, and nothing else can be voted on. The puzzle
// id is the one the site publishes (series-number); the clue id is the one in
// the puzzle file. Checked for shape rather than against the index, for the same
// reason series names are: an id that matches nothing simply counts toward
// nothing, and a second copy of the catalogue here is a copy that goes stale.
const VOTE_TARGET_RE = /^(?:c:[a-z]{4,12}-\d{1,6}:\d{1,3}-(?:across|down)|p:[a-z]{4,12}-\d{1,6})$/;
const VOTE_VERDICTS = ["up", "down"];

const INDEX_URL = "https://cryptic.paultarjan.com/puzzles/index.json";
const PUZZLE_URL = "https://cryptic.paultarjan.com/?p=";
// A phone that has not opened the site in half a year has stopped solving. The
// page re-registers on every load, so a device still in use never reaches this.
const PUSH_TTL = 60 * 60 * 24 * 180;
const MAX_SUB = 4 * 1024;
const MAX_SERIES = 12;
// Only the four push services exist. Storing an arbitrary https URL here would
// make the cron a machine that POSTs to anywhere anyone asks it to.
const PUSH_HOSTS = [".googleapis.com", ".mozilla.com", ".apple.com", ".windows.com"];
// A puzzle is announced when it first appears ANNOTATED, because the hint ladder
// is the thing worth being told about — and the annotation backlog works
// backwards through the archive, so without a window every night's catch-up
// would push a decade of Guardians at whoever subscribed that morning.
const ANNOUNCE_DAYS = 14;
// A puzzle waiting for the morning is held per subscriber, and the cap is there
// only so a device that stops being opened cannot grow an unbounded record. A
// fortnight of every paper at once does not reach it.
const MAX_HELD = 20;

const cors = (origin) => ({
  "access-control-allow-origin": origin || "*",
  "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
  "access-control-allow-headers": "content-type",
  "access-control-max-age": "86400",
});

const json = (body, status, origin) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...cors(origin) },
  });


const sha256hex = async (s) =>
  [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)))]
    .map((b) => b.toString(16).padStart(2, "0")).join("");

/* Why the request is not a subscription, or "" if it is.

   Series names are checked for SHAPE and not against a list of papers. The list
   lives in the site's own tables, and a second copy here would be a copy that
   goes stale; an unknown name simply never matches a puzzle, so the worst a
   made-up one can do is take up its own bytes. */
function badSubscription(sub) {
  if (!sub || typeof sub !== "object") return "not an object";
  if (typeof sub.endpoint !== "string") return "no endpoint";
  let host;
  try {
    const u = new URL(sub.endpoint);
    if (u.protocol !== "https:") return "endpoint is not https";
    host = u.hostname;
  } catch (e) {
    return "endpoint is not a url";
  }
  if (!PUSH_HOSTS.some((h) => host.endsWith(h))) return "not a push service";
  const k = sub.keys;
  if (!k || typeof k.p256dh !== "string" || typeof k.auth !== "string")
    return "no keys — p256dh and auth both come from the browser's subscription";
  if (!/^[\w-]{80,100}$/.test(k.p256dh) || !/^[\w-]{16,32}$/.test(k.auth))
    return "keys are not base64url of the right length";
  if (!Array.isArray(sub.series) || sub.series.length > MAX_SERIES)
    return "series must be an array of at most " + MAX_SERIES + " names";
  if (!sub.series.every((s) => typeof s === "string" && /^[a-z][a-z0-9]{1,19}$/.test(s)))
    return "a series name is not one lowercase word";
  // Both optional, and both are rejected rather than ignored when they are
  // malformed: a phone that thinks it asked for a quiet night and is woken at
  // three anyway has no way of finding out that the field never landed.
  if (sub.after && CTNotify.parseAfter(sub.after) === null)
    return "after must be a time of day like \"07:00\"";
  if (sub.tz && !CTNotify.zone(sub.tz))
    return "tz must be an IANA zone name this runtime knows, like \"America/Edmonton\"";
  return "";
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("origin") || "";
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });

    const url = new URL(request.url);

    /* Counting solves, with no solver in the data.

       THE KEY NAME IS THE RECORD. The value is empty and is never read: counting
       is a `list` by prefix, so there is no read-modify-write and therefore no
       increment a race can lose, and no counter that can end up wrong.

       A key is a date, a name from the shared list, and randomness to keep two
       of them apart. That is all of it — no address, no cookie, no id, no user
       agent, no puzzle, and no clock finer than the day. So there is nothing
       here to correlate two events into one visitor with, which is deliberate:
       the question is whether visitors solve anything, and that is an aggregate.

       Always 204, whatever was sent. A validation failure told to the caller
       would describe the list to anyone who asked, and sendBeacon has nobody to
       report an error to in any case — the page that sent this has a solver
       typing into it and must never be handed a retry. */
    if (url.pathname === "/e" && request.method === "POST") {
      const ok = new Response(null, { status: 204, headers: cors(origin) });
      if (Number(request.headers.get("content-length") || 0) > MAX_EVENT) return ok;
      const name = (await request.text()).trim();
      if (CTEvents.indexOf(name) < 0) return ok;
      const day = new Date().toISOString().slice(0, 10);
      await env.SAVES.put(`e:${day}:${name}:${crypto.randomUUID()}`, "",
                          { expirationTtl: EVENT_TTL });
      return ok;
    }

    /* What solvers thought of a clue, and of the puzzle.

       Same shape as the counting above and for the same reasons: THE KEY NAME
       IS THE RECORD, the value is empty, and a tally is a `list` by prefix, so
       two people rating the same clue in the same second cannot lose each
       other's vote. A key carries what was rated, which way, and the day — and
       nothing about who, which is why one device can be stopped from voting
       twice only by that device remembering it already did. That is the trade:
       a ballot box that cannot identify a voter cannot spot a second ballot.

       GET answers with the tally for a whole puzzle in one request — every
       clue, plus the puzzle itself — because the page needs all of it the
       moment a grid opens and thirty requests for thirty clues is not a thing
       to do to a phone.

       POST always answers 204, whatever it thought of the body, for the same
       reason /e does: there is a solver typing into the page that sent it. */
    if (url.pathname === "/v") {
      if (request.method === "POST") {
        const ok = new Response(null, { status: 204, headers: cors(origin) });
        if (Number(request.headers.get("content-length") || 0) > MAX_VOTE) return ok;
        const [target, verdict] = (await request.text()).trim().split("|");
        if (!VOTE_TARGET_RE.test(target || "")) return ok;
        if (VOTE_VERDICTS.indexOf(verdict) < 0) return ok;
        const day = new Date().toISOString().slice(0, 10);
        await env.SAVES.put(`v:${target}:${verdict}:${day}:${crypto.randomUUID()}`, "",
                            { expirationTtl: VOTE_TTL });
        return ok;
      }
      if (request.method === "GET") {
        const puzzle = url.searchParams.get("p") || "";
        if (!/^[a-z]{4,12}-\d{1,6}$/.test(puzzle))
          return json({ error: "p must be a puzzle id" }, 400, origin);
        const tally = {};
        for (const prefix of [`v:c:${puzzle}:`, `v:p:${puzzle}:`]) {
          let cursor;
          do {
            const page = await env.SAVES.list({ prefix, cursor, limit: 1000 });
            for (const k of page.keys) {
              // v:<kind>:<puzzle>[:<clue>]:<verdict>:<day>:<uuid> — the verdict
              // is always third from the end, so this does not care which kind
              // of target it is reading.
              const parts = k.name.split(":");
              const verdict = parts[parts.length - 3];
              if (VOTE_VERDICTS.indexOf(verdict) < 0) continue;
              const target = parts.slice(1, parts.length - 3).join(":");
              (tally[target] = tally[target] || { up: 0, down: 0 })[verdict]++;
            }
            cursor = page.list_complete ? null : page.cursor;
          } while (cursor);
        }
        return json(tally, 200, origin);
      }
    }

    /* A hint that is wrong, reported from the clue it is wrong on.

       Unlike /e this one ANSWERS: a reader who took the trouble to type a
       sentence is owed either a thank-you or an error, and a page that says
       "logged" over a request that failed has taught them the report goes
       nowhere. So it validates, and it says which part it did not like.

       The record is what the reporter chose to send plus the day. No address, no
       code, no clock finer than the date — the same posture as the counting
       above, for the same reason: there is nothing here to join two of these
       into one person with. */
    if (url.pathname === "/r" && request.method === "POST") {
      if (Number(request.headers.get("content-length") || 0) > MAX_REPORT)
        return json({ error: "too big" }, 413, origin);
      let r;
      try {
        const text = await request.text();
        if (text.length > MAX_REPORT) return json({ error: "too big" }, 413, origin);
        r = JSON.parse(text);
      } catch (e) {
        return json({ error: "bad json" }, 400, origin);
      }
      const str = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");
      const note = str(r && r.note, MAX_NOTE);
      if (!note) return json({ error: "empty report" }, 400, origin);
      const record = {
        puzzle: str(r.puzzle, 40), clue: str(r.clue, 24), rung: str(r.rung, 24),
        day: new Date().toISOString().slice(0, 10), note,
      };
      await env.SAVES.put(`r:${record.day}:${crypto.randomUUID()}`, JSON.stringify(record),
                          { expirationTtl: REPORT_TTL });
      return json({ ok: true }, 200, origin);
    }

    /* Who to tell about a new puzzle.

       The subscription a browser hands out IS the address, and it is a
       capability: anyone holding it can push to that phone. So it is never
       listed back out, and the key is a hash of it — the key names on their own
       are not an address. Same posture as the sync codes above: no account, no
       email, nothing here but which papers somebody reads.

       The chosen series are stored WITH the subscription because the fan-out
       has to know who wants an Everyman before it encrypts anything. A push is
       required to show a notification, so a phone woken for a paper its owner
       did not tick has nothing it can say and cannot stay silent either.

       PUT with an empty `series` is how it is turned off, so the page has one
       code path for "these are my papers" and no separate unsubscribe.

       `after` and `tz` are the quiet hours, and they travel together because
       neither means anything alone: "07:00" on a server in UTC is not seven in
       the morning anywhere the solver is. Stored as minutes past local midnight
       plus the zone, so the cron compares two numbers.

       Both are optional. A subscription without them is not held at all — see
       CTNotify.due() for why every unknown resolves that way — which is exactly
       how every subscription taken out before this existed keeps behaving until
       its device next loads the page and re-asserts with a time. */
    if (url.pathname === "/n" && request.method === "PUT") {
      if (Number(request.headers.get("content-length") || 0) > MAX_SUB)
        return json({ error: "too big" }, 413, origin);
      let sub;
      try {
        const text = await request.text();
        if (text.length > MAX_SUB) return json({ error: "too big" }, 413, origin);
        sub = JSON.parse(text);
      } catch (e) {
        return json({ error: "bad json" }, 400, origin);
      }
      const bad = badSubscription(sub);
      if (bad) return json({ error: bad }, 400, origin);

      const key = "n:s:" + (await sha256hex(sub.endpoint));
      const series = [...new Set(sub.series)];
      if (!series.length) {
        await env.SAVES.delete(key);
        return json({ ok: true, series: [] }, 200, origin);
      }
      const after = CTNotify.parseAfter(sub.after);
      const tz = CTNotify.zone(sub.tz);
      const stored = await env.SAVES.get(key, "json");
      // `until` is this record's own retirement date, written down because KV
      // will not tell you how much of a TTL is left. The cron re-writes the
      // record when it starts or clears a hold, and without this that write
      // would silently renew the 180 days on a device nobody opens any more.
      const until = Math.floor(Date.now() / 1000) + PUSH_TTL;
      await env.SAVES.put(key, JSON.stringify({
        endpoint: sub.endpoint,
        keys: { p256dh: sub.keys.p256dh, auth: sub.keys.auth },
        series, after, tz, until,
        // Anything already waiting for the morning stays waiting. This is the
        // same device asserting the same address, so dropping the queue here
        // would lose a puzzle to a page load.
        held: (stored && Array.isArray(stored.held)) ? stored.held : [],
      }), { expiration: until });
      return json({ ok: true, series, after, tz }, 200, origin);
    }

    const m = url.pathname.match(/^\/s\/([^/]+)$/);
    if (!m) return json({ error: "not found" }, 404, origin);

    const code = decodeURIComponent(m[1]).toUpperCase();
    // Validated before it is ever used as a key, so a code cannot be shaped into
    // a path or a prefix scan. There is deliberately no endpoint that lists keys.
    if (!CODE_RE.test(code)) return json({ error: "bad code" }, 400, origin);

    if (request.method === "GET") {
      const stored = await env.SAVES.get("s:" + code, "json");
      if (!stored) return json({ error: "no such code" }, 404, origin);
      return json(stored, 200, origin);
    }

    if (request.method !== "PUT") return json({ error: "method not allowed" }, 405, origin);

    const len = Number(request.headers.get("content-length") || 0);
    if (len > MAX_BODY) return json({ error: "too big" }, 413, origin);

    let incoming;
    try {
      const text = await request.text();
      if (text.length > MAX_BODY) return json({ error: "too big" }, 413, origin);
      incoming = JSON.parse(text);
    } catch (e) {
      return json({ error: "bad json" }, 400, origin);
    }
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming) ||
        !incoming.puzzles || typeof incoming.puzzles !== "object")
      return json({ error: "bad save" }, 400, origin);
    if (Object.keys(incoming.puzzles).length > MAX_PUZZLES)
      return json({ error: "too many puzzles" }, 413, origin);

    const stored = await env.SAVES.get("s:" + code, "json");
    const merged = CTMerge.mergeSaves(stored, incoming);
    // Read-merge-write is not atomic, and KV is eventually consistent anyway.
    // It does not need to be: the merge is a union, so the loser of a race is
    // re-merged by the next push from either device, and no writing order can
    // remove something that was already in.
    await env.SAVES.put("s:" + code, JSON.stringify(merged), { expirationTtl: TTL });
    return json(merged, 200, origin);
  },

  /* Every newly annotated puzzle, to everyone who ticked its paper.

     A cron rather than a call from the nightly job, because the site is a static
     deploy: "published" means the file is being served, and the only honest way
     to know that is to read the file. A puzzle annotated by hand, or a run that
     died after pushing, is then announced the same way as any other.

     The state is the set of annotated ids at the previous run, so a puzzle is
     announced the first time it becomes annotated and never again. It is written
     BEFORE anything is sent: a push service having a bad afternoon must not turn
     into the same notification every twenty minutes once it comes back.

     "Announced" is not "delivered", though, because n:seen is one global set
     while a quiet night is per subscriber. A puzzle that is news but out of
     hours for this device moves onto that device's own `held` list, and every
     run drains that list before it looks at tonight's. So n:seen answers "has
     the world been told about this puzzle" and `held` answers "does this phone
     still have it coming" — which is what stops a puzzle annotated at three in
     the morning from being marked seen and never sent.

     Delivery is AT MOST ONCE per subscriber, deliberately, and both pieces of
     state are written before the push that empties them. A run that dies
     mid-fan-out therefore loses a notification; the other ordering loses none
     and re-sends everything every twenty minutes until the push service
     recovers, which is the failure a phone actually notices. */
  async scheduled(event, env) {
    const res = await fetch(INDEX_URL, { headers: { "cache-control": "no-cache" } });
    if (!res.ok) throw new Error(`index.json: HTTP ${res.status}`);
    const index = await res.json();
    // Which paper each series belongs to, put in the index by
    // tools/fetch_puzzle.py out of tools/series.py. Absent from an index
    // deployed before that existed, and CTNotify.title() then leaves the
    // puzzle's own name alone rather than inventing a paper for it.
    const papers = index.papers || {};
    const puzzles = index.puzzles.filter((p) => p.annotated);
    const byId = new Map(puzzles.map((p) => [p.id, p]));

    const seen = await env.SAVES.get("n:seen", "json");
    await env.SAVES.put("n:seen", JSON.stringify(puzzles.map((p) => p.id)));
    if (!seen) return;   // First run of a fresh namespace: the corpus is not news.

    const known = new Set(seen);
    const now = Date.now();
    const cutoff = now - ANNOUNCE_DAYS * 24 * 60 * 60 * 1000;
    const fresh = puzzles.filter((p) => !known.has(p.id) && p.date >= cutoff);

    // No early return on an empty `fresh`: the run that delivers a held puzzle
    // at seven in the morning is by definition a run with no news of its own.
    const { keys } = await env.SAVES.list({ prefix: "n:s:" });
    if (!keys.length) return;

    const vapid = {
      jwk: JSON.parse(env.VAPID_PRIVATE_JWK),
      publicKey: env.VAPID_PUBLIC_KEY,
      subject: env.VAPID_SUBJECT,
    };
    for (const k of keys) {
      const sub = await env.SAVES.get(k.name, "json");
      if (!sub) continue;

      /* Everything this device has coming: what was held, oldest first, then
         what is new tonight. Both are re-read out of the index and re-checked
         against the CURRENT tickboxes, so a paper un-ticked while one of its
         puzzles was waiting does not arrive anyway — a push must show a
         notification, and one for a paper nobody wants has nothing to say. */
      const queue = (Array.isArray(sub.held) ? sub.held : []).concat(fresh.map((p) => p.id));
      const want = new Set(sub.series);
      const owed = [];
      for (const id of queue) {
        const p = byId.get(id);
        if (p && want.has(p.series) && owed.indexOf(id) < 0) owed.push(id);
      }

      const sendNow = CTNotify.due(sub.after, sub.tz, now);
      const held = sendNow ? [] : owed.slice(-MAX_HELD);
      // Written only when the queue actually changes, which in the ordinary
      // case — nothing held, nothing to hold — is never. Rewriting every
      // record every twenty minutes would be a write per subscriber per run
      // that changes nothing.
      if (JSON.stringify(held) !== JSON.stringify(sub.held || [])) {
        // The record's own retirement date, kept rather than renewed: KV will
        // not say how much TTL is left, so without this a device nobody opens
        // any more would have its 180 days pushed back by every hold.
        const until = Number(sub.until) || Math.floor(now / 1000) + PUSH_TTL;
        await env.SAVES.put(k.name, JSON.stringify(Object.assign({}, sub, { held, until })),
                            { expiration: until });
      }
      if (!sendNow) continue;

      for (const id of owed) {
        const p = byId.get(id);
        const status = await send(sub, JSON.stringify({
          title: CTNotify.title(p, papers),
          body: [p.setter && `Set by ${p.setter}`,
                 p.difficulty && p.difficulty.band].filter(Boolean).join(" \u00b7 "),
          url: PUZZLE_URL + p.id,
          tag: p.id,
        }), vapid);
        // The subscription is gone — app deleted, or the browser rotated it.
        // Nothing else in this run can reach it either.
        if (GONE(status)) { await env.SAVES.delete(k.name); break; }
      }
    }
  },
};
