// Does inflate.js, the gunzip app.js falls back on where a browser has no
// DecompressionStream, give back exactly what zlib compressed? Over every
// block type zlib writes (stored at level 0, fixed for short input, dynamic
// otherwise), header flags, and real shims when the checkout has them built.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const gunzip = require("../inflate.js");

const ROOT = path.join(__dirname, "..");
const cases = ["", "a", "hello hello hello hello", "x".repeat(70000)];
let seed = 7;
const rand = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
cases.push(Array.from({ length: 50000 }, () => String.fromCharCode(32 + Math.floor(rand() * 90))).join(""));
cases.push(Array.from({ length: 4000 }, () => ["across", "down", "clue", "anagram", "é", "—"][Math.floor(rand() * 6)]).join(" "));
const dir = process.env.CT_SHIM_DIR || path.join(ROOT, "puzzles");
const shims = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => /\.js$/.test(f) && f !== "index.js") : [];
for (let i = 0; i < shims.length; i += Math.max(1, Math.floor(shims.length / 300))) {
  cases.push(fs.readFileSync(path.join(dir, shims[i]), "utf8"));
}

let n = 0;
for (const text of cases) {
  const raw = Buffer.from(text, "utf8");
  for (const level of [0, 1, 6, 9]) {
    const got = Buffer.from(gunzip(new Uint8Array(zlib.gzipSync(raw, { level }))));
    assert(got.equals(raw), `level ${level}, ${raw.length} bytes: inflated to ${got.length} bytes that differ`);
    n++;
  }
}
// FNAME and FCOMMENT set, as gzip(1) writes them.
const named = Buffer.from(zlib.gzipSync(Buffer.from("named")));
named[3] = 8 | 16;
const withName = Buffer.concat([named.subarray(0, 10), Buffer.from("f.js\0note\0"), named.subarray(10)]);
assert.strictEqual(Buffer.from(gunzip(new Uint8Array(withName))).toString(), "named");
assert.throws(() => gunzip(new Uint8Array([1, 2, 3])), /not gzip/);
console.log(`test_inflate: ${n} round trips (${shims.length ? Math.min(shims.length, 300) + " real shims" : "no shims built"}) match zlib`);
