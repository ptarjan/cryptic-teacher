// Every generated page unfurls as itself: og:title, og:description, og:url,
// og:type, twitter:card, and an og:image that is an absolute, stamped,
// 1200x630 URL with alt text. A page that is not a puzzle must not borrow the
// site card (og.png, a clue from somebody else's crossword): it gets its own
// from tools/page_card.py, and its entry in og/page/cards.json must match the
// URL the page links, or make_og.sh --pages would draw a different picture.
//
// Reads the pages tools/build_seo_pages.py wrote; the cards themselves are not
// drawn in CI, so a PNG is size-checked only when it is on disk.
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const BASE = "https://cryptic.paultarjan.com/";
const fails = [];

function pages(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...pages(p));
    else if (ent.name === "index.html") out.push(p);
  }
  return out;
}

function head(file) {
  const fd = fs.openSync(file, "r");
  const buf = Buffer.alloc(16384);
  const n = fs.readSync(fd, buf, 0, buf.length, 0);
  fs.closeSync(fd);
  const text = buf.toString("utf8", 0, n);
  // The social tags come before the page's JSON-LD, which can run long.
  const end = text.indexOf("</head>");
  return end < 0 ? text : text.slice(0, end);
}

const unescape = (s) => s.replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
  .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

function meta(h, key) {
  const m = h.match(new RegExp(`<meta (?:property|name)="${key}" content="([^"]*)"`));
  return m ? unescape(m[1]) : null;
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

let cards = {};
const spec = path.join(ROOT, "og/page/cards.json");
if (fs.existsSync(spec)) cards = JSON.parse(fs.readFileSync(spec, "utf8"));
else fails.push("og/page/cards.json is missing: build_seo_pages.py writes it");

const files = [path.join(ROOT, "index.html"), ...["puzzles", "learn", "abbreviations", "indicators", "difficulty"]
  .flatMap((d) => pages(path.join(ROOT, d)))];
let checked = 0;
for (const file of files) {
  const rel = path.relative(ROOT, file);
  const h = head(file);
  const canonical = (h.match(/<link rel="canonical" href="([^"]*)"/) || [])[1];
  const own = BASE + (path.dirname(rel) === "." ? "" : path.dirname(rel) + "/");
  // A moved or retired address names another page as canonical and carries no
  // social tags: a share of it should show the card of the page it points at.
  if (canonical !== own) continue;
  checked++;
  const bad = (why) => fails.push(`${rel}: ${why}`);
  for (const key of ["og:title", "og:description", "og:type", "og:url", "og:image",
    "og:image:alt"]) {
    if (!meta(h, key) || !meta(h, key).trim()) bad(`no ${key}`);
  }
  if (meta(h, "og:url") !== canonical) bad(`og:url ${meta(h, "og:url")} is not the canonical ${canonical}`);
  if (meta(h, "twitter:card") !== "summary_large_image") bad("twitter:card is not summary_large_image");
  if (meta(h, "og:image:width") !== "1200" || meta(h, "og:image:height") !== "630")
    bad("og:image:width/height is not 1200x630");
  const image = meta(h, "og:image") || "";
  const m = image.match(/^https:\/\/cryptic\.paultarjan\.com\/([^?]+)\?v=([0-9a-f]{8})$/);
  if (!m) { bad(`og:image ${image} is not an absolute stamped URL on this site`); continue; }
  const [, img, v] = m;
  const puzzlePage = /^puzzles\/(?!series\/)[^/]+\/index\.html$/.test(rel);
  if (!puzzlePage && rel !== "index.html") {
    const slug = img.match(/^og\/page\/(.+)\.png$/);
    if (!slug) bad(`og:image is ${img}, not this page's own card`);
    else if (!cards[slug[1]] || cards[slug[1]].v !== v || cards[slug[1]].url !== canonical)
      bad(`og/page/cards.json does not hold ${img}?v=${v} for ${canonical}`);
    else if (cards[slug[1]].title !== meta(h, "og:title")) bad("the card's title is not og:title");
  }
  const png = path.join(ROOT, img);
  if (fs.existsSync(png)) {
    const [w, hgt] = pngSize(png);
    if (w !== 1200 || hgt !== 630) bad(`${img} is ${w}x${hgt}, not 1200x630`);
  }
}
if (checked < 100) fails.push(`only ${checked} pages checked: were the pages built?`);
if (fails.length) {
  console.log(`FAIL: ${fails.length} social-card problem(s)`);
  for (const f of fails.slice(0, 40)) console.log("  " + f);
  process.exit(1);
}
console.log(`social cards: ${checked} pages ok`);
