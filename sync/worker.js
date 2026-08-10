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

// No 0/O/1/I/L — this gets read off one screen and typed into another, by hand.
const CODE_RE = /^[2-9A-HJ-KMNP-TV-Z]{8}$/;
const MAX_BODY = 512 * 1024;   // ~100 puzzles of letters is a few tens of KB
const MAX_PUZZLES = 2000;
const TTL = 60 * 60 * 24 * 365; // a code untouched for a year is abandoned

const cors = (origin) => ({
  "access-control-allow-origin": origin || "*",
  "access-control-allow-methods": "GET,PUT,OPTIONS",
  "access-control-allow-headers": "content-type",
  "access-control-max-age": "86400",
});

const json = (body, status, origin) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...cors(origin) },
  });

export default {
  async fetch(request, env) {
    const origin = request.headers.get("origin") || "";
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });

    const url = new URL(request.url);
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
};
