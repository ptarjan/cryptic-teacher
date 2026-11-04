// Clue text, italics, blank clues and the letter strip's word breaks.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, assert, clueText, entryId, fs, groupsOf, path, pp, registry } = T;
// --- clue text is text, and its italics are ranges ---
// The papers ship clues as HTML. tools/fetch_puzzle.flatten_clue takes the tags
// out and keeps the italics as clue.italics {at, length} ranges, because the text
// itself has to stay plain: every annotation fragment is located in it by
// indexOf and highlighted by character offset. Structural, not a spot-check —
// the failure mode is a tag rendering as a tag, seen on the Independent, and
// it comes back the moment someone escapes a clue directly.
{
  const src = require("../app_src").read(ROOT);
  assert(!/esc\(\s*(e\.clue\.text|clueText\(e\))/.test(src),
    "no clue is escaped straight to the page — that path drops the setter's italics");
  assert(/\bclue\.italics\b/.test(src),
    "app.js reads clue.italics, so the ranges the fetchers write are actually rendered");

  /* Three sweeps in this file pick their puzzles with /^[a-z0-9]+-\d+\.json$/,
     which is a FILTER: a file whose name does not match is not reported, it is
     skipped, so a new series key of an unexpected shape would drop out of all
     three and nobody would be told. tools/series.py's puzzle_id refuses to mint
     such a key, and this says so out loud — the filter and the minter have to
     agree, and this is where that agreement is checked. */
  // Every .json in a puzzles/<series>/<year>/ folder but the authored drafts'.
  const subdirs = (d) => fs.readdirSync(d, { withFileTypes: true }).filter((e) => e.isDirectory())
    .map((e) => path.join(d, e.name));
  const puzzleFiles = subdirs(pp.PUZZLE_DIR).filter((d) => path.basename(d) !== "authored")
    .flatMap(subdirs).flatMap((y) => fs.readdirSync(y).filter((f) => f.endsWith(".json")).map((f) => path.join(y, f)));
  const files = puzzleFiles.filter((f) => /^[a-z0-9]+-\d+\.json$/.test(path.basename(f)));
  assert(files.length === puzzleFiles.length,
    "every puzzle file is named <series>-<number>.json, so the sweeps that filter on "
    + "that shape see all of them: " + puzzleFiles.filter((f) => !files.includes(f)).join(", "));
  let withItalics = 0;
  files.forEach((f) => {
    const puz = JSON.parse(fs.readFileSync(f, "utf8"));
    puz.entries.forEach((e) => {
      assert(!/<\/?[a-zA-Z][^>]*>/.test(clueText(e)),
        `${puz.id} ${entryId(e)}: clue still carries markup — ${clueText(e).slice(0, 60)}`);
      (e.clue.italics || []).forEach((r) => {
        withItalics++;
        assert(r.at >= 0 && r.length > 0 && r.at + r.length <= [...clueText(e)].length,
          `${puz.id} ${entryId(e)}: italic range ${JSON.stringify(r)} falls outside its clue`);
      });
    });
  });
  assert(withItalics > 0,
    "the italics survived the flatten — a run that finds none has thrown them away");
}

// --- a clue the paper printed blank is not a clue anyone failed to solve ---
// A paper can print a clue as nothing but whitespace and an enumeration. Unless
// that is marked, nothing downstream can tell it from a hard clue: the puzzle
// stays `annotated: false` and the nightly backfill re-spends an annotation run
// on it every night. clue.missing is written by the fetchers off ONE definition
// of wordless (fetch_puzzle.has_words) so the app never re-derives it.
{
  const src = require("../app_src").read(ROOT);
  assert(/\bclue\.missing\b/.test(src),
    "app.js reads clue.missing — otherwise a blank clue reads as 'not annotated yet', "
    + "which promises a ladder that can never be written");

  // The static page makes the same promise to the same reader.
  const seo = fs.readFileSync(path.join(ROOT, "tools", "build_seo_pages.py"), "utf8");
  assert(/\["clue"\]\.get\("missing"\)/.test(seo),
    "tools/build_seo_pages.py reads clue.missing — the puzzle page has to tell a blank "
    + "clue apart from an unwritten one, same as app.js");

  // Both renderers, and the re-fetch that would otherwise drop the note.
  const fetcher = fs.readFileSync(path.join(ROOT, "tools", "fetch_puzzle.py"), "utf8");
  ["app.js", "tools/build_seo_pages.py", "tools/fetch_puzzle.py"].forEach((f, i) => {
    assert(/missingNote/.test([src, seo, fetcher][i]),
      `${f} drops clue.missingNote — a blank clue still has a reason it gives its `
      + "answer, and only a person can write it, so nothing may silently discard it");
  });

  // Mirrors has_words() in tools/fetch_puzzle.py: any printed text is a clue,
  // punctuation included (the enumeration is not in the text).
  const hasWords = (clue) => clue.trim() !== "";
  const index = JSON.parse(fs.readFileSync(path.join(ROOT, "puzzles", "index.json"), "utf8"));
  const annotatedInIndex = new Map(index.puzzles.map((p) => [p.id, p.annotated]));
  const files = pp.puzzleFiles().filter((f) => /^[a-z0-9]+-\d+\.json$/.test(path.basename(f)));
  files.forEach((f) => {
    const puz = JSON.parse(fs.readFileSync(f, "utf8"));
    puz.entries.forEach((e) => {
      assert(hasWords(clueText(e)) === !e.clue.missing,
        `${puz.id} ${entryId(e)}: clue.missing disagrees with the clue text — ${JSON.stringify(clueText(e))}`);
      assert(!(e.clue.missing && e.annotation),
        `${puz.id} ${entryId(e)}: annotated a clue with no words in it — that explanation was invented`);
      assert(!(e.clue.missingNote && !e.clue.missing),
        `${puz.id} ${entryId(e)}: clue.missingNote on a clue that has words — it renders nowhere`);
    });
    // A puzzle whose only gaps are blank clues has to count as done, or it sits in the
    // backlog forever.
    if (annotatedInIndex.has(puz.id)) {
      const continuations = new Set(puz.entries.flatMap((e) => groupsOf(e).flatMap((grp) => grp.slice(1))));
      const answerable = puz.entries.filter((e) => hasWords(clueText(e)) && !continuations.has(entryId(e)));
      // A clue withheld for the text it still has is done too (fetch_puzzle.withheld_stands).
      const withheldStands = (e) => !e.annotation && e.annotationWithheld
        && e.annotationWithheld.clue === (e.clue.text || "");
      // A clue entered off the grid is annotated too (unannotated_clues counts it).
      assert(annotatedInIndex.get(puz.id) === (answerable.every((e) => e.annotation || withheldStands(e))
        && (puz.offGrid || []).every((item) => item.annotation)),
        `${puz.id}: index 'annotated' should count only the clues that can be annotated`);
    }
  });
}

// --- the letter strip shows where the words break ---
// The enumeration is the solver's best structural clue and the grid cannot show
// it, so the strip does. A gap in the wrong place is worse
// than no gap at all, so the parser is exercised directly and then checked
// against every answer in the corpus: wherever it claims a division, the answer
// really does break there.
{
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("const ENUM_SEPS");
  const to = src.indexOf("\n  }", src.indexOf("function enumBreaks")) + 4;
  assert(from > 0 && to > from, "enumBreaks is still in app.js to be tested");
  const enumBreaks = new Function(src.slice(from, to) + "\n  return enumBreaks;")();
  // Letters per word. An apostrophe break is dropped: it is drawn in the strip
  // but it does not start a new word, so DON'T is one four-square word either way.
  const shape = (clue, n) => {
    const b = enumBreaks(clue, n);
    if (!b) return null;
    const cuts = Object.keys(b).filter((k) => b[k] !== "’").map(Number).sort((x, y) => x - y);
    if (!cuts.length) return null;
    return cuts.map((c, i) => c - (i ? cuts[i - 1] : 0)).concat(n - cuts[cuts.length - 1]);
  };
  assert(String(shape("3,6", 9)) === "3,6", "a comma is a word break");
  assert(String(shape("3-5", 8)) === "3,5", "a hyphen breaks too");
  assert(shape("9", 9) === null, "one word gets no divisions at all");
  assert(shape(undefined, 9) === null, "no enumeration, no divisions");
  // The whole group's enumeration sits on the first leg of a linked clue, so it
  // must not be drawn over that leg's squares alone.
  assert(shape("5,4", 5) === null, "a total that misses the entry is ignored");
  assert(shape("6 and 3", 9) === null, "a worded enumeration draws no breaks");
  assert(String(shape("6.6", 12)) === "6,6", "a period where a comma was meant");

  // The leading light's own share of a linked answer: the first `length`
  // squares' worth of letters, returned only when the answer really does break
  // there. Anything else — the answer is too short, the boundary lands
  // mid-word — is a statement about the group's
  // shape rather than about the strip, and is not this check's business.
  const leadShare = (e, ans) => {
    let letters = 0, cut = -1;
    for (let i = 0; i < ans.length; i++) {
      if (!/[ \-–'’]/.test(ans[i])) letters++;
      if (letters === e.length) { cut = i + 1; break; }
    }
    if (cut < 0 || cut >= ans.length) return null;
    return /[ \-–]/.test(ans[cut]) ? ans.slice(0, cut) : null;
  };

  pp.puzzleFiles().filter((f) => /^[a-z0-9]+-\d+\.json$/.test(path.basename(f))).forEach((f) => {
    const puz = JSON.parse(fs.readFileSync(f, "utf8"));
    puz.entries.forEach((e) => {
      const ans = e.annotation && e.annotation.answer;
      const drawn = shape(e.clue.enumeration, e.length);
      if (!ans || !drawn) return;
      // A linked group's answer is stored whole on its leading light, but the
      // strip is drawn over that light's own squares. Usually the paper
      // enumerates the whole group there too and shape() has already returned
      // null, the total missing the entry; Private Eye sometimes enumerates
      // the leading light alone, and then the strip is dividing that light's
      // share of the answer and only that share is what it can be checked
      // against. A continuation reads "see 16dn." and has no enumeration at all.
      const text = e.group ? leadShare(e, ans) : ans;
      if (text === null) return;
      // An apostrophe occupies no square, and the Guardian counts HOW'S as four
      // — so it is taken out of both sides rather than compared. An enumeration
      // may legitimately divide an answer that is written solid, (1,1,1) for
      // I.C.I., so only answers that really are several words are compared.
      const real = text.replace(/['’]/g, "").split(/[ \-–]/).filter(Boolean).map((w) => w.length);
      if (real.length < 2) return;
      assert(String(drawn) === String(real),
        `${puz.id} ${entryId(e)}: strip would break ${drawn} but ${text} breaks ${real}`);
    });
  });

  // --- and it shrinks to fit rather than stacking one word per line ---
  // Fourteen boxes at full size are wider than a phone, and flexbox moves a whole
  // word to the next line rather than shrinking anything, so (3,8,3) would come
  // out as three almost-empty rows on a phone screen. CSS cannot count letters,
  // so the strip publishes its own shape and the stylesheet does the arithmetic.
  // Both halves are pinned here because either alone is silently useless: markup
  // with nothing reading it, or a rule sizing off a variable nobody sets.
  const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  const strip = registry["hint-pattern"].innerHTML;
  const n = /--n:\s*(\d+)/.exec(strip), w = /--w:\s*(\d+)/.exec(strip);
  assert(n && w, "the letter strip publishes --n and --w for the stylesheet: " + strip.slice(0, 120));
  const words = (strip.match(/class="pat-word /g) || []).length;   // the trailing space skips the last, unbroken one
  assert(Number(w[1]) === words,
    `--w counts the word breaks actually drawn: ${w[1]} vs ${words}`);
  // Both patterns keep their trailing space: without it "pat-box" also matches
  // the "pat-boxes" wrapper and every count here is one too many.
  assert(Number(n[1]) === (strip.match(/class="pat-box /g) || []).length,
    `--n counts the boxes actually drawn: ${n[1]}`);
  assert(/\.pat-box[^{]*\{[^}]*100cqw[^}]*var\(--n/.test(css.replace(/\/\*[\s\S]*?\*\//g, "")),
    "and .pat-box sizes itself off --n against the container width");
  assert(/\.pattern[^{]*\{[^}]*container-type:\s*inline-size/.test(css),
    "which needs .pattern to be the query container, or 100cqw is the viewport");
}
