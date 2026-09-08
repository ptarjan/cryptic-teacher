/* The cron fan-out, run for real against a fake KV and a fake network.

     node tools/test_push_hold.js

   sync/notify.js's arithmetic is checked in tools/smoke_test.js, and that is
   the easy half. The half that actually loses a notification is the bookkeeping
   around it: n:seen is written BEFORE the fan-out, so a puzzle held for the
   morning has already been marked as announced to the world and exists nowhere
   but the subscriber's own queue. Get that wrong and a puzzle annotated at
   three in the morning is silently never delivered — no error, no retry, and
   nothing to notice for months.

   So this drives scheduled() itself, four times, across a night. Everything
   below the Worker is real: the merge of the queue, the encryption in
   sync/webpush.js, the VAPID signature. Only two things are faked, and they are
   the two the test could not otherwise own — KV, which is a Map here, and
   fetch, which serves the index and swallows the pushes. No push leaves this
   process, which is the point: the subscriptions in the real namespace are
   phones on people's bedside tables.

   ESM because sync/worker.js is a Worker module and cannot be require()d;
   tools/smoke_test.js shells out to this rather than importing it. */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import worker from "../sync/worker.js";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const INDEX = JSON.parse(fs.readFileSync(path.join(ROOT, "puzzles/index.json"), "utf8"));

const b64url = (bytes) => Buffer.from(bytes).toString("base64")
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

// A subscriber's real keys and a real VAPID pair, so sync/webpush.js does the
// whole derivation rather than being handed something it rejects.
const ua = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
const vapidPair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign"]);
const keys = {
  p256dh: b64url(await crypto.subtle.exportKey("raw", ua.publicKey)),
  auth: b64url(crypto.getRandomValues(new Uint8Array(16))),
};
const env = {
  VAPID_PRIVATE_JWK: JSON.stringify(await crypto.subtle.exportKey("jwk", vapidPair.privateKey)),
  VAPID_PUBLIC_KEY: b64url(await crypto.subtle.exportKey("raw", vapidPair.publicKey)),
  VAPID_SUBJECT: "mailto:nobody@example.com",
};

// Two puzzles from two papers, dated now so they are inside the announce
// window, on top of an index where everything else is already seen.
let clock = Date.parse("2026-09-08T09:00:00Z");   // 03:00 in Edmonton, in September
const realNow = Date.now;
Date.now = () => clock;

const fresh = [
  { id: "cryptic-99001", series: "cryptic", name: "Cryptic crossword No 99,001",
    setter: "Paul", annotated: true, date: clock, difficulty: { band: "Tough" } },
  { id: "everyman-99002", series: "everyman", name: "Everyman crossword No 99,002",
    setter: "Everyman", annotated: true, date: clock, difficulty: null },
];
const index = { ...INDEX, puzzles: [...fresh, ...INDEX.puzzles] };

const pushed = [];
globalThis.fetch = async (url, init) => {
  if (String(url).endsWith("index.json")) return { ok: true, json: async () => index };
  pushed.push({ url: String(url), bytes: (init.body || []).length });
  return { status: 201 };
};

const kv = new Map();
const expirations = new Map();
const SAVES = {
  async get(key, type) {
    const v = kv.get(key);
    return v === undefined ? null : (type === "json" ? JSON.parse(v) : v);
  },
  async put(key, value, opts) { kv.set(key, value); expirations.set(key, opts || {}); },
  async delete(key) { kv.delete(key); },
  async list({ prefix }) {
    return { keys: [...kv.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })) };
  },
};
env.SAVES = SAVES;

kv.set("n:seen", JSON.stringify(INDEX.puzzles.filter((p) => p.annotated).map((p) => p.id)));
const RETIRES = Math.floor(clock / 1000) + 60 * 60 * 24 * 180;
// One subscriber who asked to be left alone until seven, and one saved before
// any of that existed — no `after`, no `tz`, no queue.
kv.set("n:s:quiet", JSON.stringify({
  endpoint: "https://web.push.apple.com/quiet", keys,
  series: ["cryptic", "everyman"], after: 420, tz: "America/Edmonton",
  until: RETIRES, held: [],
}));
kv.set("n:s:legacy", JSON.stringify({
  endpoint: "https://web.push.apple.com/legacy", keys, series: ["cryptic"],
}));

const to = (who) => pushed.filter((p) => p.url.endsWith(who)).length;
const heldNow = () => JSON.parse(kv.get("n:s:quiet")).held;

// --- 03:00 local: the puzzles are news, and one subscriber is asleep ---
await worker.scheduled({}, env);
check(to("quiet") === 0, "03:00 — the subscriber who asked for 07:00 is not woken");
check(to("legacy") === 1,
  "03:00 — a subscription saved before quiet hours existed is sent at once: " + to("legacy"));
check(JSON.stringify(heldNow()) === JSON.stringify(["cryptic-99001", "everyman-99002"]),
  "03:00 — both puzzles are on that subscriber's queue: " + JSON.stringify(heldNow()));
check(expirations.get("n:s:quiet").expiration === RETIRES,
  "and the record keeps its own retirement date — a hold must not renew the 180 days");
// The whole hazard in one line: the world has been told, so nothing but the
// queue above can still deliver these.
check(JSON.parse(kv.get("n:seen")).includes("cryptic-99001"),
  "03:00 — and n:seen already counts the held puzzle as announced");

// --- 04:00, nothing new. Still silent, and no write that changes nothing ---
clock += 60 * 60 * 1000;
const quiet4 = kv.get("n:s:quiet");
await worker.scheduled({}, env);
check(to("quiet") === 0 && to("legacy") === 1, "04:00 — a run with no news sends nothing");
check(kv.get("n:s:quiet") === quiet4, "and does not rewrite a queue that has not changed");

// --- 09:00, still nothing new. The night's puzzles arrive, named ---
clock = Date.parse("2026-09-08T15:00:00Z");
await worker.scheduled({}, env);
check(to("quiet") === 2, "09:00 — both held puzzles are delivered: " + to("quiet"));
check(JSON.stringify(heldNow()) === "[]", "and the queue is emptied");

// --- 09:20, nothing new. Nothing arrives twice ---
clock += 20 * 60 * 1000;
await worker.scheduled({}, env);
check(to("quiet") === 2, "09:20 — exactly once per subscriber: " + to("quiet"));
check(to("legacy") === 1, "for the subscriber with no quiet hours too: " + to("legacy"));

// --- a paper un-ticked while its puzzle waited must not arrive anyway ---
clock = Date.parse("2026-09-09T09:00:00Z");   // 03:00 again
const late = { id: "everyman-99003", series: "everyman", name: "Everyman crossword No 99,003",
  setter: "Everyman", annotated: true, date: clock, difficulty: null };
index.puzzles.unshift(late);
await worker.scheduled({}, env);
check(JSON.stringify(heldNow()) === JSON.stringify(["everyman-99003"]), "a later night queues again");
kv.set("n:s:quiet", JSON.stringify({ ...JSON.parse(kv.get("n:s:quiet")), series: ["cryptic"] }));
clock = Date.parse("2026-09-09T15:00:00Z");   // 09:00
await worker.scheduled({}, env);
check(to("quiet") === 2, "and a paper un-ticked while its puzzle waited is dropped, not sent");
check(JSON.stringify(heldNow()) === "[]", "leaving nothing behind on the queue");

Date.now = realNow;
console.log(failures ? `\n${failures} FAILURE(S)` : "\nPUSH HOLD TEST PASSED");
process.exit(failures ? 1 : 0);
