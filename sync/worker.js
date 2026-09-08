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

const INDEX_URL = "https://paultarjan.com/cryptic-teacher/puzzles/index.json";
const PUZZLE_URL = "https://paultarjan.com/cryptic-teacher/?p=";
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
       code path for "these are my papers" and no separate unsubscribe. */
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
      await env.SAVES.put(key, JSON.stringify({
        endpoint: sub.endpoint,
        keys: { p256dh: sub.keys.p256dh, auth: sub.keys.auth },
        series,
      }), { expirationTtl: PUSH_TTL });
      return json({ ok: true, series }, 200, origin);
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
     into the same notification every twenty minutes once it comes back. */
  async scheduled(event, env) {
    const res = await fetch(INDEX_URL, { headers: { "cache-control": "no-cache" } });
    if (!res.ok) throw new Error(`index.json: HTTP ${res.status}`);
    const puzzles = (await res.json()).puzzles.filter((p) => p.annotated);

    const seen = await env.SAVES.get("n:seen", "json");
    await env.SAVES.put("n:seen", JSON.stringify(puzzles.map((p) => p.id)));
    if (!seen) return;   // First run of a fresh namespace: the corpus is not news.

    const known = new Set(seen);
    const cutoff = Date.now() - ANNOUNCE_DAYS * 24 * 60 * 60 * 1000;
    const fresh = puzzles.filter((p) => !known.has(p.id) && p.date >= cutoff);
    if (!fresh.length) return;

    const vapid = {
      jwk: JSON.parse(env.VAPID_PRIVATE_JWK),
      publicKey: env.VAPID_PUBLIC_KEY,
      subject: env.VAPID_SUBJECT,
    };
    const { keys } = await env.SAVES.list({ prefix: "n:s:" });
    for (const k of keys) {
      const sub = await env.SAVES.get(k.name, "json");
      if (!sub) continue;
      for (const p of fresh) {
        if (!sub.series.includes(p.series)) continue;
        const status = await send(sub, JSON.stringify({
          title: p.name,
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
