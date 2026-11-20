/**
 * Extract a filler-ready word list from the Lufz lexicon.
 *
 * Lufz (https://github.com/viresh-ratnakar/lufz, MIT) is UKACD18 — the classic
 * British cryptic word list — cleaned up and augmented: entries are ordered by
 * Wikipedia-derived importance, so a word's INDEX is a fairness score, and each
 * entry carries CMUdict pronunciations, which is what makes a homophone hook a
 * real phonetic claim rather than a guess.
 *
 * The lexicon ships as browser globals (24 MB of it), so we load it in a vm
 * context with a two-line document shim and call Exet's own init. Doing the
 * extraction here rather than in Python keeps tools/grid_fill.py dependency-free
 * and means the 24 MB blob is only ever read once.
 *
 * Output: tools/data/lexicon.tsv, one line per single-word lowercase entry:
 *     word <TAB> rank <TAB> gb <TAB> family <TAB> phone-key
 * rank is the lexicon index (1 = "the"); gb is 0 for a spelling the Britain
 * region replaces (COLOR, KILOMETERS, THEATER) and 1 otherwise; family is the
 * size of the word's stem group (EARTH has 40 relatives, ERIC has 2 — a decent
 * proxy for how embedded in English a word is, and so for how many senses it
 * might carry); phone-key is the first CMUdict pronunciation with stress digits
 * stripped ("" when unknown). Everything else — charades, containers, anagram
 * grouping, homophone grouping — is derived from those columns by
 * tools/clueability.py.
 *
 * Deliberately dropped: capitalised entries (Lufz marks proper nouns by case,
 * and a daily cryptic grid should not lean on them), multi-word phrases,
 * hyphens and apostrophes.
 *
 * Usage: node tools/build_lexicon.js [path-to-data-dir]
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const TOOLS = __dirname;
const DATA = process.argv[2] || path.join(TOOLS, 'data');
const OUT = path.join(TOOLS, 'data', 'lexicon.tsv');

const FILES = ['lufz-en-lexicon.js', 'lufz-en-lexicon-stems.js', 'exet-lexicon.js'];

function main() {
  const missing = FILES.filter((f) => !fs.existsSync(path.join(DATA, f)));
  if (missing.length) {
    console.error(`missing ${missing.join(', ')} in ${DATA}\n` +
                  `run: bash tools/fetch_lexicon.sh`);
    process.exit(2);
  }
  // The lexicon files are browser scripts: they assign globals and Exet's init
  // touches document. This shim is the whole of what they need.
  const ctx = { document: { getElementById: () => null }, console, TextEncoder, TextDecoder };
  vm.createContext(ctx);
  for (const f of FILES) {
    vm.runInContext(fs.readFileSync(path.join(DATA, f), 'utf8'), ctx, { filename: f });
  }
  vm.runInContext('exetLexiconInit()', ctx);
  const lex = ctx.exetLexicon;

  // The Britain region lists (British form, its non-British counterpart) pairs.
  // A Guardian grid should not answer KILOMETERS or THEATER, so the second of
  // each pair is flagged and the filler drops it.
  const nonBritish = new Set();
  const region = lex.regions && lex.regions.Britain;
  for (const [, b] of (region ? region.swaps : [])) nonBritish.add(lex.lexicon[b]);

  const out = [];
  for (let i = 1; i < lex.lexicon.length; i++) {
    const w = lex.lexicon[i];
    if (!/^[a-z]{2,15}$/.test(w)) continue;  // drops proper nouns and phrases
    const phones = (lex.phones && lex.phones[i] && lex.phones[i][0]) || null;
    // Stress digits (AH0 vs AH1) distinguish emphasis, not sound; homophones
    // must ignore them or MINUTE/MINUTE-style pairs never group.
    const key = phones ? phones.map((p) => String(p).replace(/[0-9]/g, '')).join(' ') : '';
    // stems[] is a cycle through the word's morphological family.
    let family = 1;
    if (lex.stems) {
      for (let j = lex.stems[i]; j !== i && family < 64; j = lex.stems[j]) family++;
    }
    out.push(`${w.toUpperCase()}\t${i}\t${nonBritish.has(w) ? 0 : 1}\t${family}\t${key}`);
  }
  fs.writeFileSync(OUT, `#lufz ${lex.id}\twords=${out.length}\n${out.join('\n')}\n`);
  console.error(`wrote ${OUT} — ${out.length} words from ${lex.id}, ` +
                `${nonBritish.size} non-British spellings flagged`);
}

main();
