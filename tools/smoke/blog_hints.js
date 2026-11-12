// Hints that come from a blog's facts rather than our annotation.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { CLIMBABLE, CTQuotes, ROOT, allPuzzles, assert, btnNames, clueText, confirmArmed, entryId,
  fs, isAsking, openFromPicker, path, pickerRowFor, pp, registry, shape, takeRung } = T;
// --- a clue we have not explained still gets the hints a blog marked ---
// tools/blog_facts.py reads the definition a blogger underlined and the clue type
// they named; the shim carries them and the ladder is built from them in our
// own words. It says whose marks those are, and links to the full write-up.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // A definition read off the letters is ours, and badged so (blogHintsBadge).
  const blogDef = (e) => !e.annotation && e.blog && (e.blog.definitions || []).length === 1
    && !(e.blog.inferred || []).includes("definitions");
  const target = allPuzzles.find((p) => !p.annotated && puzzles[p.id] && puzzles[p.id].blog
    && puzzles[p.id].entries.some(blogDef));
  if (shape("an un-annotated puzzle with blog facts", target)) {
    const puz = puzzles[target.id];
    const e = puz.entries.find(blogDef);
    // As the page prints it: "Big Dave's" arrives as "Big Dave&#39;s".
    const blogName = puz.blog.name.replace(/&/g, "&amp;").replace(/'/g, "&#39;");
    if (openFromPicker(target.id)) {
      assert(registry["puzzle-title"].innerHTML.includes("hints via " + blogName),
        `${target.id}'s title names the blog its hints come from: ${registry["puzzle-title"].innerHTML}`);
      registry["clue-" + entryId(e)].listeners.click[0]();
      assert(registry["hint-meter"].innerHTML.includes("hints via " + blogName + " · ours to come"),
        `${target.id} ${entryId(e)}: the meter badges blog-derived hints as standing in for ours`);
      assert(registry["hint-escape"].innerHTML.includes(`href="${puz.blog.url}"`)
        && registry["hint-escape"].innerHTML.includes("Full explanation on " + blogName),
        `${target.id} ${entryId(e)}: links to the full write-up: ${registry["hint-escape"].innerHTML}`);
      const def = registry["hint-next"].children.find((b) => /Where is the definition/.test(b.textContent));
      if (assert(def, `${target.id} ${entryId(e)}: has a definition rung: ${btnNames()}`)) {
        takeRung(def);
        const shown = CTQuotes.curl(e.blog.definitions[0].text);
        assert(registry["hint-body"].innerHTML.includes(`<mark class="def">${shown}</mark>`)
          || registry["hint-body"].innerHTML.includes(shown.replace(/&/g, "&amp;")),
          `${target.id} ${entryId(e)}: the definition rung names the blog's definition`);
        assert(registry["hint-clue"].innerHTML.includes('class="def'),
          `${target.id} ${entryId(e)}: the definition is marked in the clue`);
      }
      // What the blog marked includes its WORD (clue words) blocks, so the
      // blocks rung is there exactly when this clue has one; the walkthrough
      // is the blogger's and never ours to write.
      // A block that is the whole answer is held back as ours are, unless it
      // is a hidden word's carrier, which shows its note instead.
      const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
      const sol = bare(e.solution);
      const shown = (e.blog.blocks || []).filter(({ gives, clueFragment: frag }) => bare(gives) !== bare(frag)
        && (bare(gives) !== sol || sol.length >= 3
          && (bare(frag).includes(sol) || bare(frag).includes([...sol].reverse().join("")))));
      assert(!registry["hint-next"].children.some((b) => /Full walkthrough/.test(b.textContent)),
        `${target.id} ${entryId(e)}: a blog ladder stops at what the blog marked: ${btnNames()}`);
      assert(registry["hint-next"].children.some((b) => /building blocks/.test(b.textContent)) === shown.length > 0,
        `${target.id} ${entryId(e)}: a building-blocks rung exactly when the blog wrote blocks: ${btnNames()}`);
    }
  }
}

// --- a hidden word's carrier, from the blog facts, reads as ours do ---
// letter_facts.py writes a hidden word's one block, {clueFragment: the clue
// words that carry it, gives: the answer}. The rung holds its letters back, the whole answer, and shows
// the carrier with the run in capitals, the note our own hidden words carry;
// and the question in front of it never names the letters either.
// Blog facts live one sidecar a puzzle: puzzles/<series>/<year>/<id>.blog, keyed by id.
// Streamed one file at a time: holding the whole archive parsed costs ~350 MB.
function* blogSidecars() {
  const base = path.join(ROOT, "puzzles");
  for (const s of fs.readdirSync(base).sort()) {
    const sd = path.join(base, s);
    if (!fs.statSync(sd).isDirectory()) continue;
    for (const y of fs.readdirSync(sd).sort()) {
      const yd = path.join(sd, y);
      if (!fs.statSync(yd).isDirectory()) continue;
      for (const n of fs.readdirSync(yd).sort()) {
        if (n.endsWith(".blog")) yield [n.slice(0, -5), JSON.parse(fs.readFileSync(path.join(yd, n), "utf8"))];
      }
    }
  }
}
// The blog ladder is what the app builds for a clue we have NOT annotated, and
// the hint burn annotates puzzles newest-first, so the corpus eventually holds
// no such clue for a given blog shape. The checks below therefore do not hunt
// for an un-annotated clue: they take a sidecar fact whose clue is annotated
// or not and make the clue un-annotated in memory, as fetch_puzzle.with_blog_facts
// ships it (no annotation, the fact as `blog`), before the app opens the puzzle.
function asUnannotated(pid, eid, fact) {
  const meta = allPuzzles.find((p) => p.id === pid);
  if (!meta) return false;
  if (!global.window.CRYPTIC_PUZZLES[pid]) {
    new Function("window", fs.readFileSync(path.join(ROOT, "puzzles", meta.file), "utf8"))(global.window);
  }
  const puz = global.window.CRYPTIC_PUZZLES[pid];
  const e = puz && (puz.entries || []).find((x) => entryId(x) === eid);
  if (!e) return false;
  delete e.annotation;
  e.blog = fact;
  puz.blog = puz.blog || { name: "smoke blog", url: "https://example.com/" };
  return true;
}
{
  const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
  let target = null;
  for (const f of [0]) {
    for (const [pid, rec] of blogSidecars()) {
      const file = pp.find(pid);
      if (!file) continue;
      const ents = JSON.parse(fs.readFileSync(file, "utf8")).entries;
      const hit = Object.entries(rec.entries).find(([eid, fa]) => JSON.stringify(fa.type) === '["hidden_word"]'
        && (fa.blocks || []).length === 1 && !(fa.indicators || []).length
        && ents.some((x) => entryId(x) === eid && x.solution && bare(x.solution) === bare(fa.blocks[0].gives)
          && clueText(x).includes(fa.blocks[0].clueFragment)));
      if (hit && asUnannotated(pid, hit[0], hit[1])) { target = { pid, eid: hit[0], answer: bare(hit[1].blocks[0].gives) }; break; }
    }
    if (target) break;
  }
  if (assert(target, "the blog facts hold a hidden word with its carrier") && openFromPicker(target.pid)) {
    const { pid, eid, answer } = target;
    registry["clue-" + eid].listeners.click[0]();
    for (let guard = 0; guard < 6; guard++) {
      const next = registry["hint-next"].children.find(CLIMBABLE);
      if (!next || /building blocks/.test(next.textContent)) break;
      takeRung(next);
    }
    const rung = registry["hint-next"].children.find((b) => CLIMBABLE(b) && /building blocks/.test(b.textContent));
    if (assert(rung, `${pid} ${eid}: the carrier makes a building-blocks rung: ${btnNames()}`)) {
      rung.onclick();
      confirmArmed();
      const ask = registry["hint-body"].innerHTML;
      assert(!ask.includes(`<span class="gives">${answer}</span>`),
        `${pid} ${eid}: the question does not name ${answer}: ${ask}`);
      if (isAsking(registry["hint-body"])) { registry["guess-tell"].onclick(); confirmArmed(); }
      const body = registry["hint-body"].innerHTML;
      assert(/hidden (?:backwards )?in /.test(body) && !body.includes(`<span class="gives">${answer}</span>`),
        `${pid} ${eid}: the carrier shows its note and holds back ${answer}: ${body}`);
    }
  }
}

// --- a blog's homophone reads as ours do: the word heard, then held back ---
// blog_facts.py keeps the word a write-up says a homophone's clue words are
// heard as (TUN for TON) as the block's soundsLike, as our annotations do; the
// rung shows it "said aloud" and, the block being the whole answer, not the answer.
{
  const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
  let target = null;
  for (const f of [0]) {
    for (const [pid, rec] of blogSidecars()) {
      const hit = Object.entries(rec.entries).find(([, fa]) => JSON.stringify(fa.type) === '["homophone"]'
        && (fa.blocks || []).length === 1 && /^[A-Z]+$/.test(fa.blocks[0].soundsLike || ""));
      if (!hit) continue;
      const file = pp.find(pid);
      const e = file && JSON.parse(fs.readFileSync(file, "utf8")).entries.find((x) => entryId(x) === hit[0]);
      if (e && e.solution && clueText(e).includes(hit[1].blocks[0].clueFragment) && asUnannotated(pid, hit[0], hit[1])) {
        target = { pid, eid: hit[0], answer: bare(e.solution), heard: hit[1].blocks[0].soundsLike };
        break;
      }
    }
    if (target) break;
  }
  if (assert(target, "the blog facts hold a homophone with the word heard") && openFromPicker(target.pid)) {
    const { pid, eid, answer, heard } = target;
    registry["clue-" + eid].listeners.click[0]();
    for (let guard = 0; guard < 6; guard++) {
      const next = registry["hint-next"].children.find(CLIMBABLE);
      if (!next || /building blocks/.test(next.textContent)) break;
      takeRung(next);
    }
    const rung = registry["hint-next"].children.find((b) => CLIMBABLE(b) && /building blocks/.test(b.textContent));
    if (assert(rung, `${pid} ${eid}: the heard block makes a building-blocks rung: ${btnNames()}`)) {
      takeRung(rung);
      const body = registry["hint-body"].innerHTML;
      assert(body.includes(`<span class="gives">${heard}</span> <span class="muted">said aloud</span>`)
        && !body.includes(`<span class="gives">${answer}</span>`),
        `${pid} ${eid}: the rung says ${heard} is heard and holds back ${answer}: ${body}`);
    }
  }
}

// --- a clue type read off the letters is not credited to the blog ---
// tools/letter_facts.py fills in a type the blog left out, marked "inferred".
// A clue with nothing else from the blog is badged as ours, not the blog's.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const hit = (p) => (puzzles[p.id].entries || []).find((x) => !x.annotation && x.blog
    && (x.blog.inferred || []).includes("type") && x.blog.typeCore
    && !(x.blog.definitions || []).length && !(x.blog.blocks || []).length && !(x.blog.indicators || []).length);
  const target = allPuzzles.find((p) => !p.annotated && puzzles[p.id] && puzzles[p.id].blog && hit(p));
  if (shape("an un-annotated clue whose only blog fact is an inferred core type", target)
      && openFromPicker(target.id)) {
    const e = hit(target);
    registry["clue-" + entryId(e)].listeners.click[0]();
    const meter = registry["hint-meter"].innerHTML;
    assert(meter.includes("hints from the letters") && !meter.includes("hints via "),
      `${target.id} ${entryId(e)}: an inferred type is not badged as the blog's: ${meter}`);
  }
}

// --- a blog's building blocks read like ours ---
// "TAKE (arrange) + COVER (insurance)" ships as {clueFragment, gives} blocks,
// and the blocks rung shows them the way it shows an annotation's: the clue
// words, an arrow, the letters.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
  // A hidden word's one block is its carrier, the whole answer: the hidden
  // rung shows that, not a blocks rung.
  const piece = (x) => ({ gives, clueFragment: frag }) => bare(gives) !== bare(frag) && bare(gives) !== bare(x.solution);
  const hit = (p) => (puzzles[p.id].entries || []).find((x) => !x.annotation && x.blog
    && (x.blog.blocks || []).some(piece(x)));
  const target = allPuzzles.find((p) => !p.annotated && puzzles[p.id] && puzzles[p.id].blog && hit(p));
  if (shape("an un-annotated clue with blog blocks", target) && openFromPicker(target.id)) {
    const e = hit(target);
    registry["clue-" + entryId(e)].listeners.click[0]();
    for (let guard = 0; guard < 20; guard++) {
      const btn = registry["hint-next"].children.find(CLIMBABLE);
      if (!btn) break;
      takeRung(btn);
    }
    const { gives, clueFragment: frag } = e.blog.blocks.find(piece(e));
    // The page sets apostrophes typographically: "Savalas's" shows as "Savalas’s".
    const body = registry["hint-body"].innerHTML.replace(/’/g, "'");
    assert(body.includes(`“${frag.replace(/’/g, "'")}”`) && body.includes(`<span class="gives">${gives}</span>`),
      `${target.id} ${entryId(e)}: the blocks rung shows “${frag}” → ${gives}: ${body.slice(0, 400)}`);
  }
}

// --- a puzzle we solved ourselves says so ---
// Prize crosswords get solved here before the paper publishes its key
// (tools/apply_solution.py), which means the app will happily tell a solver
// their letter is wrong on the authority of a machine's guess. The disclosure
// is the whole justification for shipping those answers at all, so it is
// asserted rather than trusted: it is one badge on the puzzle title that one
// line of app.js appends, easy to lose in a refactor nothing else notices.
{
  const unofficial = allPuzzles.find((p) => p.solutionsUnofficial && global.window.CRYPTIC_PUZZLES[p.id]);
  if (unofficial) {
    registry["btn-picker"].onclick();
    const row = pickerRowFor(unofficial.id);
    assert(row && row.children[0].innerHTML.includes("unverified answers"),
      `the picker badges No ${unofficial.number} as unverified`);
    row.children[0].onclick();
    const title = registry["puzzle-title"].innerHTML;
    assert(/unverified answers/.test(title),
      `No ${unofficial.number} badges its title as unverified: ` + title);
    assert(/hasn't published|not published/.test(title),
      "the badge says the paper hasn't published these answers: " + title);
    // Nor on a blog's published solve: every Times Quick answer is read off
    // timesforthetimes, which anyone can look up, so none of them is ours.
    const blogBadged = allPuzzles.filter((p) => p.series === "timesquick" && p.solutionsUnofficial);
    assert(blogBadged.length === 0,
      `no blog-sourced puzzle is badged unverified: ${blogBadged.map((p) => p.id).slice(0, 5)}`);
    // And the badge must not appear on a puzzle with the paper's own answers.
    const official = allPuzzles.find((p) => p.hasSolutions && !p.solutionsUnofficial
      && global.window.CRYPTIC_PUZZLES[p.id]);
    openFromPicker(official.id);
    assert(!/unverified answers/.test(registry["puzzle-title"].innerHTML),
      `No ${official.number} has the paper's answers and shows no badge`);
  }
}

// --- an unattributed puzzle names no setter ---
// A source that ships no byline has no setter key. Both the picker row and the
// puzzle title leave the setter out entirely rather than print "null".
{
  const anon = allPuzzles.find((p) => !("setter" in p) && global.window.CRYPTIC_PUZZLES[p.id]);
  if (anon) {
    const row = openFromPicker(anon.id);
    assert(row && !/null|undefined/.test(row.children[0].innerHTML),
      `No ${anon.number}'s picker row prints no setter`);
    const title = registry["puzzle-title"].innerHTML;
    assert(!/set by|null|undefined/.test(title),
      `No ${anon.number} has no known setter, so its title says nothing about one: ` + title);
  }
}
