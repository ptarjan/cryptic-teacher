"use strict"; // app part 5 of 7 (incremental redraw, score, stats, fireworks). Classic script sharing the page scope with its siblings; see tools/app_src.js.
  // ---------- writing only what changed ----------
  //
  // The panel is rebuilt by refreshAll(), and refreshAll() runs on every
  // keystroke. Assigning innerHTML makes the browser throw the subtree away,
  // reparse it and lay the block out again, so a letter typed into the grid
  // would repaint a hint panel in which nothing had changed — the block shivers
  // under the typing, worst on iOS.
  //
  // The rule for everything in this panel: never write DOM that would come out
  // the same. Each region is built into a value first — a string, or for the
  // button row a list the row is a pure function of — and written only when
  // that value differs from the one it was last built from. Compared against
  // what we wrote rather than against el.innerHTML, because a browser hands
  // back its own re-serialisation and the two would never match.
  //
  // Skipping the write means skipping the handler wiring that goes with it, and
  // that is only sound because the nodes are still there with their handlers
  // live. The other half of the bargain: NO HANDLER IN THIS PANEL MAY CLOSE
  // OVER STATE THAT THE COMPARED VALUE DOES NOT CONTAIN. Each one re-reads the
  // current entry and the current guess when it fires, so a handler that
  // outlives several renders still answers for now.
  function setHTML(el, html) {
    if (el._shown === html) return false;
    el._shown = html;
    el.innerHTML = html;
    return true;
  }

  // The rung row is data first and DOM second, for the same reason the rest of
  // the panel is a string first: a row that is a pure function of this list can
  // be compared as a list and left alone. It stays real elements rather than
  // markup because these buttons carry handlers and a label that must not be
  // re-escaped by hand.
  function setButtons(el, spec) {
    const key = JSON.stringify(spec);
    if (el._shown === key) return false;
    el._shown = key;
    el.innerHTML = "";
    spec.forEach((b) => {
      // Built like every other button, because nothing in this row may be
      // written with innerHTML: that throws away the children already appended
      // in the same pass. This one is offered from the moment the blocks rung
      // opens, so it is always appended ALONGSIDE "Next building block" and the
      // rungs, never instead of them.
      if (b.fill) {
        const hx = document.createElement("button");
        hx.id = "hx-entry";
        hx.textContent = b.text;
        if (b.cls) hx.className = b.cls;
        if (b.arm) hx.setAttribute("data-arm", b.arm);
        hx.onclick = (ev) => {
          const on = currentEntry();
          if (fillCosts(on) && !confirmBlock(on, "fill", ev)) return;
          fillAnswer();
        };
        el.appendChild(hx);
        return;
      }
      const btn = document.createElement("button");
      if (b.cls) btn.className = b.cls;
      btn.textContent = b.text;
      if (b.title) btn.title = b.title;
      if (b.arm) btn.setAttribute("data-arm", b.arm);
      if (b.disabled) { btn.disabled = true; el.appendChild(btn); return; }
      btn.onclick = (ev) => {
        // Ask before telling, where the clue can pose the question. Not once
        // the clue is solved: the rungs have stopped being hints by then and
        // quizzing someone on an answer they already have is a chore.
        // The previous rung's verdict stays where it is: clearing it would delete
        // a block from the middle of the panel at the exact moment a new one
        // appeared at the bottom, so the whole thing would slide under the
        // solver's eyes. Nothing the panel has said is ever taken back; it only
        // ever grows.
        const on = currentEntry();
        if (!on) return;
        // Which piece this button is for. Only the blocks rung has more than
        // one, and only its "next piece" button sets it; everything else asks
        // its single question at step 0.
        const at = b.step || 0;
        const asked = GUESSABLE[b.rung] && !isEntrySolved(on) && guessAsk(on, b.rung, at);
        // A building block that would cost a hint takes a second tap.
        if (b.rung && !asked && rungCosts(on, b.rung, false)
            && !confirmBlock(on, b.rung === "blocks" ? "blocks-" + at : b.rung, ev)) return;
        if (asked) {
          guessing = { key: entryKey(on), rung: b.rung, step: at, picked: [],
                       slots: (asked.pairs || []).map(() => -1), held: -1, heldSlot: -1 };
          focusHint("guess");
        } else {
          // Whatever was being asked is off the table: this button is the
          // solver saying they want this rung instead, and a question left
          // hanging under the rung they just took would be answered by it.
          guessing = null;
          focusHint(b.rung);
          // Free by elimination: shown and earned, so the meter does not move.
          if (b.rung === "blocks" && !isShown(on, "blocks") && !groupSolved(on) && blocksFree(on, at)
              && earnedRungs(on).indexOf("blocks") < 0) earnedRungs(on).push("blocks");
          showHint(on, b.rung);
          // A piece with no question in it — no fragment to point at, or no
          // letters to point at it with — is simply handed over. The rung still
          // moves forward by exactly one.
          if (b.rung === "blocks") revealPiece(on, at);
        }
        refreshAll();
      };
      el.appendChild(btn);
    });
    return true;
  }

  // The question currently on the table, re-derived rather than captured, so a
  // handler that survived a skipped rebuild grades what is being asked now.
  function currentAsk() {
    const e = currentEntry();
    if (!e || !guessing || guessing.key !== entryKey(e)) return null;
    return guessAsk(e, guessing.rung, guessing.step);
  }

  // Reporting a hint that is wrong, from the clue it is wrong on. It lives in the
  // strip the reveal button is already in rather than getting a page or a form:
  // a reader who has just been taught something false is two taps from saying so,
  // and there is no address to find and nothing to sign up for. What goes with it
  // is only what the site already knows — which clue, and which rung was open.
  let report = null;   // { key, phase: "open" | "sent" | "failed", msg }
  function reportHTML() {
    if (!report) return `<button id="rp-open" class="ghost small">Report a bad hint</button>`;
    if (report.phase === "sent") return `<span class="muted">Thanks — noted.</span>`;
    // The reason, not "try again later": a reader told only that it failed cannot
    // tell an outage from something they did.
    if (report.phase === "failed") {
      return `<span class="muted">Couldn’t send (error: ${esc(report.msg)}).</span> `
        + `<button id="rp-open" class="ghost small">Try again</button>`;
    }
    // A box you can see what you wrote in: the 400 characters this accepts need
    // more than one line, or the start of your own sentence scrolls out of sight
    // while you finish it. It opens at two lines and grows with
    // the text; Send is the button, because in a box this shape Enter is a
    // paragraph break and not a submit.
    return `<textarea id="rp-note" class="rp-note" rows="2" maxlength="400"`
      + ` placeholder="What’s wrong with this hint?"></textarea>`
      + `<button id="rp-send" class="ghost small">Send</button>`;
  }
  function sendReport(e) {
    const el = $("rp-note");
    const note = ((el && el.value) || "").trim();
    if (!note) return;
    const key = entryKey(e);
    fetch(SYNC_ENDPOINT.replace(/\/$/, "") + "/r", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ puzzle: P && P.id, clue: entryId(e),
                             rung: shownRungs(e).slice(-1)[0] || "", note }),
    }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      report = { key, phase: "sent" };
      refreshAll();
    }).catch((err) => {
      report = { key, phase: "failed", msg: (err && err.message) || String(err) };
      refreshAll();
    });
  }
  // Takes no entry, on purpose. These handlers are bound behind setHTML, which
  // rewrites nothing when the new markup equals the old — and the escape hatch's
  // markup is identical for every unsolved, revealable clue whose report is not
  // open, which is most of them. So moving between two such clues rebinds
  // nothing, and a handler that had closed over the entry it was bound on would
  // still be answering for that one several clues later: the report would be
  // filed against a clue the reader had left. That is the rule stated over
  // setHTML — no handler in this panel may close over state the compared value
  // does not contain — so each handler reads the current entry at the moment
  // of the click rather than being rebound more often.
  function bindReport() {
    const open = $("rp-open");
    if (open) open.onclick = () => {
      report = { key: entryKey(currentEntry()), phase: "open" };
      refreshAll();
    };
    const send = $("rp-send");
    if (send) send.onclick = () => sendReport(currentEntry());
    const note = $("rp-note");
    if (note && note.addEventListener) {
      // The box follows the text rather than making you scroll inside it. CSS
      // caps the height; past that it scrolls, which is the point at which you
      // have written more than the strip can hold.
      const grow = () => {
        if (typeof note.scrollHeight !== "number") return;
        note.style.height = "auto";
        note.style.height = note.scrollHeight + "px";
      };
      note.addEventListener("input", grow);
      note.addEventListener("keydown", (ev) => {
        // Enter breaks a line here. Ctrl/Cmd+Enter still sends, for the hands
        // that expect it, but the Send button is the way this is meant to go.
        if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) sendReport(currentEntry());
      });
    }
  }

  // The marks the clue line was last drawn with — see the entrance animation in
  // renderHintPanel.
  let lastMarkSig = null;
  // Where a clue's hints are read off a blog, or it has none of ours at all,
  // the blogger's own write-up is one tap away, beside the other ways out of a
  // clue. The badge says whose marks the rungs were built from, the way
  // "unverified answers" says whose answers the checker uses.
  function blogLinkHTML(e, ann) {
    if (!P.blog || (ann && !ann.fromBlog) || e.clue.missing) return "";
    return `<a class="blog-link small" href="${esc(P.blog.url)}" target="_blank" rel="noopener">Full explanation on ${esc(P.blog.name)} →</a>`;
  }
  // Credits the blog with what it marked and nothing else: a definition, a type,
  // indicators or a block read off the letters (ann.inferred, block.inferred) are
  // said to be ours, and a clue whose hints are all ours is not badged with the blog's name.
  function blogHintsBadge(ann) {
    const name = esc(P.blog.name);
    const ours = (ann.inferred || []).includes("type");
    const ourDef = (ann.inferred || []).includes("definitions");
    const ourInds = (ann.inferred || []).includes("indicators");
    const ourBlocks = ann.blocks.some((b) => b.inferred);
    const theirs = !!(((ann.definitions || []).length && !ourDef) || (ann.indicators.length && !ourInds) || ann.blocks.some((b) => !b.inferred) || (ann.type.length && !ours));
    const items = [ourDef && "definition", ours && "clue type", ourInds && "indicators", ourBlocks && (ann.blocks.every((b) => b.inferred) ? "pieces" : "some pieces")].filter(Boolean);
    const which = (items.length > 1 ? items.slice(0, -1).join(", ") + " and " + items[items.length - 1] : items[0]) || "clue type";
    const are = ourBlocks || ourInds || items.length > 1 ? "are" : "is";
    if (!theirs) return ` <span class="badge auto letters" title="We haven't explained this clue ourselves yet, and ${name} marked nothing in it. Its ${which} ${are} worked out from the letters of the clue and the answer.">hints from the letters</span>`;
    const what = ourDef || ours || ourInds || ourBlocks ? `what ${name} marked in its write-up, put into our own words. The ${which} ${are} not ${name}'s: worked out from the letters of the clue and the answer`
      : `the definition and clue type that ${name} marked in its write-up, put into our own words`;
    // Provisional, and says so: once we annotate the clue, with_blog_facts drops
    // the blog's facts and our own ladder takes this one's place.
    return ` <span class="badge auto blog" title="We haven't explained this clue ourselves yet. These hints are ${what}. Our own full hint replaces them once we write it.">hints via ${name} · ours to come</span>`;
  }

  // The selected clue on one line above the grid, for a phone, where the panel
  // that carries it is below the fold. CSS shows it only at phone width.
  function renderClueStrip(e) {
    const el = $("clue-strip");
    if (!el) return;
    setHTML(el, e && !jigsaw ? `<b>${e.offGrid ? "" : esc(tag(e))}</b> ${plainClueHTML(holderOf(e))}` : "");
  }

  // Paul 11-08: "I want to be able to select words right off the bat without a
  // click and then the definition without a click." Arriving at a clue asks the
  // ladder's first free question straight away, so its words are tappable with
  // no button in between. The same nextQuestion the right-answer chain uses, so
  // the same limits hold: only a question (asking is free and charges nothing,
  // so the "no hints" score cannot move), never a rung that costs, never the
  // walkthrough, never on a solved clue. Once per arrival, keyed by the clue: a
  // wrong answer, "Skip for now" or "Just tell me" leaves the clue where the
  // solver put it, and only coming back to it asks again.
  //
  // Two things it leaves alone. The rest of a building-blocks rung already
  // open: each piece's question names what the piece gives, so asking it on
  // arrival hands over letters the solver did not reach for, and going on to
  // the next piece stays their call. And a first visit while the tour is still
  // on its welcome or its "these buttons are hints" line: that line is teaching
  // the row, and a question over it would answer a lesson that was not given.
  let arrivedAt = null;
  function arriveAt(e) {
    const key = e ? entryKey(e) : null;
    if (key === arrivedAt) return;
    arrivedAt = key;
    if (!e || guessing) return;
    const line = typeof nux === "number" ? NUX_LINES[nux] : null;
    if (line && (line.id === "welcome" || line.id === "ladder")) return;
    const n = nextQuestion(e);
    if (n && !(n.rung === "blocks" && isShown(e, "blocks"))) advanceLadder(e);
  }

  function renderHintPanel() {
    const e = currentEntry();
    renderClueStrip(e);
    const panel = $("hint-panel");
    if (!e) {
      arrivedAt = null;
      // A square only an unclued light covers has no clue to hint at, but it
      // still has the escape hatch.
      const light = currentLight();
      if (!light) { panel.classList.add("hidden"); return; }
      panel.classList.remove("hidden");
      guessing = null;
      ["hint-pattern", "hint-meter", "hint-body", "hint-vote"].forEach((id) => setHTML($(id), ""));
      setHTML($("hint-clue"), `<span class="entry-tag">Unclued</span>`);
      setButtons($("hint-next"), []);
      const open = canCheck() && !paperHides() && light.some((c) => c.letter !== c.sol);
      if (setHTML($("hint-escape"), open ? letterBtnHTML(null) : "") && open) {
        $("hx-letter").onclick = letterTap;
      }
      return;
    }
    panel.classList.remove("hidden");

    const holder = holderOf(e);
    const ann = annOf(e);
    const key = entryKey(e);
    const level = shownRungs(e).filter((r) => r !== ANSWER_RUNG).length;

    const solved = isEntrySolved(e);
    // The nod lands beside the clue as well as on the grid. celebrateSolve tints
    // the cells for 450ms, which is a thing you miss entirely if you were reading
    // the clue while you typed the last letter into it.
    // So this one does not expire: it is a standing mark that
    // the clue is out, and arriving late still finds it. A clue solved with
    // nothing bought gets the gold star, anything else the green check — the
    // same glyph and the same two tiers the clue list uses, so one mark means
    // one thing wherever it is drawn.
    let clueLine = jigsaw ? "" : `<span class="entry-tag">${e.offGrid ? "Off the grid" : tag(e)}</span>`;
    if (solved) {
      const clean = noHintsSolve(e);
      clueLine += `<span class="clue-done${clean ? " clean" : ""}" title="${
        clean ? "Solved with no hints at all" : "Solved"}">${clean ? "★" : "✓"}</span>`;
    }
    if (holder !== e && !jigsaw) clueLine += `<span class="muted">(one answer whose letters are divided between ${tag(e)} and ${tag(holder)}; its clue is printed at ${tag(holder)} and shown here) </span>`;
    // The strip shows the grid's letters in the clue's squares: in a jigsaw,
    // where the answer goes.
    setHTML($("hint-pattern"), jigsaw || e.offGrid ? "" : patternHTML(e));
    // On paper the panel is the clue and its letters, and nothing that could
    // say whether they are right: no meter, no ladder, no reveal, no vote.
    if (paperHides()) {
      guessing = null;
      arrivedAt = key;
      setHTML($("hint-clue"), clueLine + pickableClueHTML(holder, null, [], null));
      ["hint-meter", "hint-body", "hint-escape", "hint-vote"].forEach((id) => setHTML($(id), ""));
      setButtons($("hint-next"), []);
      return;
    }

    // A report is about the clue it was started on, and moving on abandons it —
    // the same rule the guess follows, for the same reason.
    if (report && report.key !== key) report = null;
    const reveals = revealsUsed[key] || 0;
    const revealsNote = reveals ? ` · ${reveals} letter${reveals > 1 ? "s" : ""} revealed` : "";
    // The count the score charges, not the number of rungs currently on screen:
    // once solved you can open the rest for free, and the meter has to say the
    // same thing the scorebar does or one of them is lying.
    const charged = hintsCharged(e);
    const meterHTML = solved
      ? ((charged || reveals)
          ? `Solved with ${charged} hint${charged === 1 ? "" : "s"}${revealsNote}`
          : "Solved with no hints at all")
      // "used on this clue" — you are looking at the clue. Just the count: a
      // rung you answered yourself is not charged for. What you worked out is
      // reported beside it, because that is the number this is all for.
      : (ann ? `<strong>${level}</strong>/${ladderSteps(ann, clueText(e)).length} hints shown${
                 earnedRungs(e).length ? ` · ${earnedRungs(e).length} of those worked out by answering its question, so free` : ""}${revealsNote}`
             : revealsNote.replace(" · ", ""));
    // Whether there is anything left on the ladder, filled in below once the
    // steps are known: a solved clue's score is settled, so the rest of the
    // ladder costs nothing. The explanation of a clue you have already
    // got is the one thing this site is for; the reader has to be told they can
    // have it.
    let freeRest = false;

    const body = $("hint-body");
    const next = $("hint-next");
    const escape = $("hint-escape");
    let bodyHTML = "";
    const nextSpec = [];
    let ask = null, tapping = false;

    if (!ann) {
      arrivedAt = key;
      // Two different silences, and telling them apart is the whole point.
      // "Not annotated yet" promises a ladder that is coming; a clue the paper
      // printed blank has no ladder ever, because there is no clue. Say which,
      // or the reader hunts the grid for wordplay that was never printed.
      // clue.missing is written by the fetchers off has_words — see fetch_puzzle.
      // A blank clue printed on purpose still yields its answer, and saying
      // only "the space came through empty" leaves the reader staring at an
      // answer with no reason for it. clue.missingNote is where a person writes
      // that reason; the annotation queue cannot, having no words to read.
      bodyHTML = e.clue.missing
        ? `<div class="hint-step"><p class="muted">The paper printed this clue blank —
        the space was empty in every copy, not just yours. ${e.clue.missingNote
          ? esc(e.clue.missingNote)
          : "Nothing was left to solve with, so there is no wordplay to explain."}
        ${canCheck() ? "You can reveal the answer below." : ""}</p></div>`
        : `<div class="hint-step"><p class="muted">This clue hasn’t been explained yet
        (<span class="badge auto">answers only</span>), so it has no hints.
        You can still check your letters${canCheck() ? " and reveal the answer below" : ""}.</p></div>`;
      if (canCheck() && !solved) nextSpec.push(fillSpec(e, "Reveal answer"));
    } else {
      // Revealed rungs always read in ladder order and keep their ladder
      // number, whatever order they were asked for in. The numbering is the
      // teaching sequence, not a click log — a solver who took 4 before 2 has
      // still met them as steps 2 and 4, and gaps in the numbers show what
      // they skipped.
      const steps = ladderSteps(ann, clueText(e));
      // A guess belongs to the clue it was asked about. Moving on abandons it —
      // carrying it would mean checking an answer against a different question.
      if (guessing && guessing.key !== key) guessing = null;
      if (lastGuess && lastGuess.key !== key) lastGuess = null;
      arriveAt(e);
      // Computed before the rungs are drawn, not after them: an earlier rung's
      // verdict has to know whether the clue line above is currently a set of
      // buttons, and that is only knowable from the question being asked now.
      ask = guessing ? guessAsk(e, guessing.rung, guessing.step) : null;
      if (guessing && !ask) guessing = null;
      tapping = !!(ask && !ask.choices && !ask.pairs && guessing && holder === e);
      // The blocks rung as much of it as has been handed over. A solved clue
      // gets the lot: its score is settled, and the rest of the ladder is free
      // from that moment, so there is nothing left for the pacing to protect.
      const paced = (s) => {
        // Each fact once: with the blocks listed above, the walkthrough keeps only
        // how they join.
        if (s.key === "walkthrough" && s.afterBlocks && isShown(e, "blocks") && (solved || !piecesLeft(e))) {
          return { ...s, html: s.afterBlocks };
        }
        if (s.key === "type" && s.formula) {
          // After the rung's own line and its rule chip, not inside them.
          // Once the blocks rung is open it draws the same formula, as taps.
          return isShown(e, "blocks") ? { ...s, formula: undefined, after: "" }
            : { ...s, after: formulaHTML(e, s.formula, false) };
        }
        if (s.key !== "blocks" || !s.pieces) return s;
        const formula = s.formula ? formulaHTML(e, s.formula, true) : "";
        // The pieces that are out, in clue order, however they came out: the
        // count reaching them, or a chip in the formula taking them early.
        const out = s.pieces.filter((_, k) => solved || pieceOut(e, k));
        // The type rung already named and explained the mechanism when it is open.
        const lead = isShown(e, "type") && !s.leadAlways ? "" : s.lead;
        return { ...s, html: lead + `<ul>${out.join("")}</ul>`
                             + (out.length >= s.pieces.length ? s.tail : ""),
                 after: formula };
      };
      steps.forEach((s, i) => {
        if (!isShown(e, s.key)) return;
        // The verdict reads above the rung it judged: you find out whether you
        // were right, and then you are told, in that order. It keeps the marked
        // clue with it, so what you pointed at and what was actually there can
        // be read side by side against the explanation, for as long as you like.
        let chunk = "";
        if (lastGuess && lastGuess.rung === s.key) chunk += verdictHTML(lastGuess, tapping);
        chunk += hintStepHTML(paced(s), i + 1, earnedRungs(e).indexOf(s.key) >= 0,
          rulesOpen.has(entryKey(e) + "|" + s.key));
        // The verdict travels with the rung it judged, so the anchor goes round
        // both: you were told whether you were right, and then told why.
        bodyHTML += hintFocus === s.key ? `<div id="hint-focus">${chunk}</div>` : chunk;
      });
      // The legend is built from what is actually highlighted, not keyed off one
      // rung, so taking the indicators alone still explains their marks.
      const legend = [];
      if (isShown(e, "definition") && (ann.definitions || []).length) legend.push('<mark class="def">definition</mark>');
      if (isShown(e, "indicators") && (ann.indicators || []).length) {
        legend.push('<mark class="ind">indicator</mark>');
      }
      if (isShown(e, "definition") && (ann.linkWords || []).length) {
        legend.push('<mark class="link">link words</mark>');
      }
      if (legend.length) {
        bodyHTML += `<div class="legend">${legend.join(LIST_SEP)} highlighted in the clue above</div>`;
      }

      // A rung that has been asked for but not yet handed over: the solver is
      // being asked to point at the words first. It goes last in the body, under
      // everything they have already bought, because that is where the next
      // thing to do has always been.
      // How the ladder works, said once and then never again: it stops the
      // moment a rung is worked out anywhere in this puzzle, because at that
      // point it has been demonstrated and repeating it is just noise on every
      // clue you open after. Only claimed when a rung on THIS clue really can
      // ask; a clue with no question in it must not be sold as one. Above the
      // question when one was asked on arrival: that question arrived unasked,
      // and this is the sentence that says why it is there and what it is worth.
      if (!bodyHTML && !solved && !Object.keys(hintsEarned).some((k) => hintsEarned[k].length)
          && steps.some((s) => GUESSABLE[s.key] && guessAsk(e, s.key))) {
        bodyHTML = `<div class="hint-step"><p class="muted">Each hint asks you a question before it tells you —
          answer it yourself and the hint is free.</p></div>`;
      }
      if (ask) {
        const at = steps.map((s) => s.key).indexOf(guessing.rung);
        const q = guessHTML(ask, at + 1, steps[at].label, holder === e);
        bodyHTML += hintFocus === "guess" ? `<div id="hint-focus">${q}</div>` : q;
      }



      // Every unlocked rung is offered at once, not just the next one: wanting
      // the indicators shouldn't mean being handed the definition on the way,
      // since working out where the definition sits is most of the skill. The
      // recommended one still leads and still says "hint N", so the taught path
      // costs one obvious click and a sideways move costs one deliberate one.
      // Rungs from a later tier are shown but disabled rather than hidden — the
      // ladder has a shape and the solver should be able to see it coming.
      // A question on the table does not close the row. The rungs are not a
      // quiz, they are a ladder you are standing on, and a solver who wants a
      // different step is not cheating their way past this one — they have
      // decided this is not the question they needed. Taking another rung
      // abandons the guess and charges for the rung, which is what it would have
      // cost anyway; the abandoned question was never answered, so nothing is
      // earned by walking away from it.
      const togo = steps.map((s, i) => ({ s, n: i + 1 })).filter(({ s }) => !isShown(e, s.key));
      const open = togo.filter(({ s }) => rungAvailable(e, steps, s.key));
      // The rest of a rung already open, and it leads: finishing what you
      // started is the recommended move, ahead of buying the next rung. It is
      // not a new rung and does not cost one — the price was paid when the rung
      // was taken. Gone once the last piece is out, and never offered on a
      // solved clue, whose whole ladder is already open and free.
      const left = !solved && isShown(e, "blocks") ? piecesLeft(e) : 0;
      if (left) {
        const total = blockPieces(e).length;
        // The piece is already paid for, so the walk follows it: this button
        // leads the row, and a light that skipped it would go dark in the
        // middle of the one rung that takes several presses.
        // The first piece not out, which is the count unless the formula took
        // pieces ahead of it.
        const next = nextPiece(e);
        const arm = "blocks-" + next;
        const armed = armedFor(e, arm);
        nextSpec.push({ rung: "blocks", step: next, arm,
          cls: (nuxPointsAtRung() ? "rung-point" : "") + (armed ? " arm-cost" : ""),
          text: armed ? ARMED_TEXT : `Next building block · ${next + 1} of ${total}` });
      }
      open.forEach(({ s, n }, j) => {
        // Every rung reads as its own question and nothing else, not as an
        // answer you buy. What it is recommending is still visible: the lead is
        // the plain button and the sideways moves are ghosts.
        // "Free" rides on the button, not only in the meter above it. Once the
        // clue is solved its score is settled and the rest of the ladder is
        // free, but the decision to open one is made at the button, and a button
        // that reads the same as it did when it charged is not telling you.
        // The welcome dialog says "take the first one"; this is which one that
        // is. Only while the cursor is still on the ladder line, so it stops at
        // the first hint along with the sentence that asked for it.
        // The building blocks, where taking them costs, carry the two-tap
        // confirm (blocksCost): armed, the button says what the next tap does.
        const arm = s.key === "blocks" ? "blocks-0" : s.key;
        const armed = armedFor(e, arm);
        const freeBlocks = s.key === "blocks" && !solved && !guessAsk(e, "blocks", 0) && blocksFree(e, 0);
        nextSpec.push({ rung: s.key, arm,
          cls: (j || left ? "ghost small" : (nuxFreeRung(e, s.key, solved) ? "rung-point" : "")) + (solved ? " free" : "")
            + (armed ? " arm-cost" : ""),
          text: armed ? ARMED_TEXT : `${n} · ${s.label}${solved || freeBlocks ? " · free" : ""}` });
      });
      togo.filter((t) => open.indexOf(t) < 0).forEach(({ s, n }) => {
        nextSpec.push({ cls: "ghost small locked", disabled: true, text: `${n} · ${s.label}`,
          title: "Open the hints above first — this one would give them away" });
      });
      freeRest = solved && togo.length > 0;
      // Offered once the building blocks are up, not only once the whole ladder
      // is: the blocks spell the answer out piece by piece, so a solver who has
      // just assembled it is being made to copy their own work into the grid
      // square by square. Still offered last, under the rungs,
      // because it is the way out of the clue rather than a step in it.
      if (!guessing && canCheck() && !solved && (!togo.length || isShown(e, "blocks"))) {
        nextSpec.push(fillSpec(e, FILL_LABEL));
      }
    }
    // The free wheel sits under whatever the ladder has shown. Not drawn while
    // the paid ring is on screen: two rings would share one set of letters and
    // one #ana-shuffle id, and the paid one already does the job.
    const wheelOpen = freeWheel === key && !solved && !bodyHTML.includes("anagram-ring");
    if (wheelOpen) bodyHTML += freeRingHTML(e, ann);
    // Written last, because whether its words are targets is decided by whether a
    // question ended up being asked. A linked clue is the exception and keeps the
    // second copy: the words being asked about are this entry's own clue, and the
    // one on display belongs to the entry it is linked with.
    //
    // Chip-wrapped either way — see pickableClueHTML — so tapping starting or
    // ending never changes this element's own box, only the colour of the
    // border round each word.
    clueLine += tapping
      ? pickableClueHTML(e, ask, guessing.picked, guessing.rung)
      : pickableClueHTML(holder, null, [], null, wheelOpen && holder === e ? (ring.words || {}) : null);
    // The marks fade in, which is an arrival: it must play when a mark arrives
    // and at no other time. Picking words rewrites the clue too — the picked
    // word's class is in the markup — so every <mark> comes back as a new element
    // on every tap and would replay the fade. setHTML's markup comparison
    // cannot tell those apart, because the markup really did change.
    //
    // So the animation is gated on a class, like .picking below, and the class
    // is decided by the MARKS. Set before the write, not after: the elements
    // that animate are created by that write, and a class arriving afterwards
    // would start a fade and then cancel it.
    const markSig = clueText(holder) + "\n" + JSON.stringify(clueMarks(holder));
    $("hint-clue").classList.toggle("marks-new", markSig !== lastMarkSig);
    lastMarkSig = markSig;
    const clueWrote = setHTML($("hint-clue"), clueLine);
    // Only for the reveal flash (see .hint-clue.picking in style.css) — the
    // clue's own size is fixed regardless of which form is in it, so this
    // class carries no metric that setHTML's markup comparison would need to
    // catch. Set on the element rather than baked into the markup, or the
    // flash would replay every re-render mid-guess instead of firing once.
    // Gated on tapping itself, not on the markup containing "guess-clue" —
    // that substring is in the resting render too since both forms share the
    // same chip markup, so it cannot tell picking apart from reading.
    $("hint-clue").classList.toggle("picking", tapping);

    setHTML($("hint-meter"), meterHTML + (freeRest ? " · the remaining hints are free now" : "")
      + (ann && ann.fromBlog ? blogHintsBadge(ann) : ""));

    const bodyWrote = setHTML(body, bodyHTML);
    setButtons(next, nextSpec);

    // And once the answer is out, what did you make of it? Its own slot at the
    // foot of the panel, not the end of #hint-body: appended to the body it would
    // sit wherever the body happened to end, directly under the clue on a clue
    // solved cold and a screen further down with four rungs taken. The thing
    // you do when you have finished is last in the panel,
    // and last is a place that does not move.
    const voteWrote = setHTML($("hint-vote"),
      solved && ann ? voteRowHTML(voteTarget(e), "Good clue?", "Yes", "Not really") : "");

    // The escape hatch lives outside the ladder: available at any level.
    // No "(counts against your score)" rider: the scorebar already reports
    // revealed letters, and a learner who is stuck should be nudged toward the
    // help rather than taxed for taking it.
    const canReveal = canCheck() && !solved;
    const escapeHTML = (canReveal
      ? letterBtnHTML(e) + " " : "")
      // On every unsolved clue, whatever its type, and not a hint: it holds
      // only what the solver types into it.
      + (solved ? "" : `<button id="hx-wheel" class="ghost small" aria-pressed="${wheelOpen}">${
          wheelOpen ? "Hide letter wheel" : "Letter wheel"}</button> `)
      + reportHTML() + blogLinkHTML(e, ann);
    if (setHTML(escape, escapeHTML)) {
      if (canReveal) $("hx-letter").onclick = letterTap;
      bindReport();
    }
    // Bound on EVERY render, not only when the row's markup changes: two
    // unsolved clues draw the same row, so moving between them keeps the old
    // button, and a handler bound once would still hold the first clue's key —
    // the wheel would open on that clue instead of this one.
    const hw = $("hx-wheel");
    if (hw) hw.onclick = () => {
      freeWheel = wheelOpen ? null : key;
      // The wheel's letters are picked off the clue's own words, so a question
      // that was asked on arrival steps aside for it rather than keeping them.
      if (freeWheel) guessing = null;
      // Focus first so the ring's focus outline is on the first draw and
      // the solver can type straight away, as a tap on the disc does.
      const ak = $("ana-kbd");
      if (freeWheel && ak) focusHidden(ak);
      renderHintPanel();
    };

    if (!bodyWrote && !clueWrote && !voteWrote) return;

    if (ask && ask.choices) {
      ask.choices.forEach((c, i) => {
        $("gc-" + i).onclick = () => {
          const a = currentAsk();
          if (a && a.choices) finishGuess(gradeChoice(a, c), a);
        };
      });
    } else if (ask && ask.pairs) {
      // Either half may be tapped first. A chunk then a row, or a row then a
      // chunk: both are one pairing, and a tap that only worked in one
      // order would be a dead tap in the other. Whichever is tapped first is
      // the one held.
      ask.chips.forEach((c, i) => {
        const el = $("gm-chip-" + i);
        if (el) el.onclick = () => {
          if (!currentAsk()) return;
          if (guessing.heldSlot >= 0) {
            guessing.slots[guessing.heldSlot] = i;
            guessing.heldSlot = -1; guessing.held = -1;
          } else {
            guessing.held = guessing.held === i ? -1 : i;
            guessing.heldSlot = -1;
          }
          renderHintPanel();
        };
      });
      ask.pairs.forEach((p, i) => {
        $("gm-slot-" + i).onclick = () => {
          if (!currentAsk()) return;
          // A slot with something in it gives it back; the pick-up is the
          // undo, so there is no separate clear button to find.
          if (guessing.slots[i] >= 0) {
            guessing.held = guessing.slots[i]; guessing.slots[i] = -1; guessing.heldSlot = -1;
          } else if (guessing.held >= 0) {
            guessing.slots[i] = guessing.held; guessing.held = -1; guessing.heldSlot = -1;
          } else {
            guessing.heldSlot = guessing.heldSlot === i ? -1 : i;
          }
          renderHintPanel();
        };
      });
      $("guess-check").onclick = () => {
        const a = currentAsk();
        if (!a || !a.pairs || !guessing.slots.every((n) => n >= 0)) return;
        finishGuess(gradeMatch(a, guessing.slots), a);
      };
    } else if (ask) {
      // Only the words in play have a button to bind: a settled one is a span.
      ask.tokens.forEach((t, i) => {
        if (ask.known.indexOf(i) >= 0) return;
        const el = $("gw-" + i);
        el.onclick = () => {
          // A drag ends in a click on the word it started from. That click has
          // already been answered by the drag.
          if (swallowClick) { swallowClick = false; return; }
          const a = currentAsk();
          if (!a) return;
          const j = guessing.picked.indexOf(i);
          if (j >= 0) guessing.picked.splice(j, 1); else guessing.picked.push(i);
          // Repainted in place, exactly as a drag across the same words already
          // is. A tap changes which words are lit and whether the check button
          // is live, and nothing else on the page says either — so rebuilding
          // the panel to report it would mark the clue up again, rewrite three
          // blocks of HTML and rebind every word, under the finger that had
          // just tapped. On a phone that is long enough to read as a tap that
          // missed.
          paintPicked(a);
          spotlightDraw();
        };
        if (el.addEventListener) {
          el.addEventListener("pointerdown", (ev) => {
            // A new gesture starts clean. swallowClick is set on pointerup and
            // read by the click that follows it, and a drag whose finger lifts
            // off the words sends no click at all — so without this it would stay
            // set until the next tap, which it would then eat.
            swallowClick = false;
            const a = currentAsk();
            if (a) {
              drag = { base: guessing.picked.slice(), from: i, moved: false, ask: a,
                       x: (ev && ev.clientX) || 0, y: (ev && ev.clientY) || 0 };
            }
          });
        }
      });
      $("guess-check").onclick = () => {
        const a = currentAsk();
        if (!a || !guessing.picked.length) return;
        finishGuess(gradeGuess(a), a);
      };
    }
    // Never a dead end. Asking to be told is a legitimate answer to "do you know
    // this yet?", and it costs what the rung has always cost. Every question has
    // one, whether it is answered by tapping words or by picking a family.
    //
    // And never a toll gate either. The tap that opens a question was a tap on
    // the ladder — "show me this rung" — so a solver who reads the question and
    // does not like their odds must be able to put it back down: a charade
    // whose letters do not obviously belong to any one fragment is a coin
    // flip, and a rung staked on it would be a toll. Nothing was shown, so
    // nothing is spent and nothing is earned; the rung goes back on the ladder
    // and asks again.
    if (ask) {
      $("guess-tell").onclick = (ev) => {
        const a = currentAsk();
        if (!a) return;
        const on = currentEntry();
        if (rungCosts(on, guessing.rung, true) && !confirmBlock(on, guessing.rung + "-tell", ev)) return;
        finishGuess(null, a);
      };
      $("guess-later").onclick = () => {
        if (!currentAsk()) return;
        guessing = null;
        refreshAll();
      };
    }

    wireVotes(panel, renderHintPanel);

    // The anagram ring. Both handlers only ever touch `ring`, so a redraw is
    // the whole update — the tiles are where the letters are, not what they are.
    //
    // A TILE MUST NOT TAKE FOCUS. #ana-kbd's blur handler redraws the ring (so
    // the focus outline goes away), and a tap that steals focus therefore
    // destroys the very button it is a tap on before the click can be
    // dispatched: the keyboard would drop and the letter would never be
    // crossed off. Refusing the default
    // mousedown — the synthesised one iOS sends before click — is what keeps
    // the focus, and the tile, where they were. Shuffle needs it for the same
    // reason.
    const keepFocus = (ev) => ev.preventDefault();
    panel.querySelectorAll("button.ana-tile").forEach((b) => {
      b.onmousedown = keepFocus;
      b.onclick = () => {
        const i = b.getAttribute("data-ana");
        if (ring) {
          tapRingTile(i);
          // A tap on a tile is also "I might type next" — #ana-kbd is focused
          // first so the ring's focus ring is already drawn on the redraw that
          // follows, the same order addRingLetter/removeLastRingLetter use.
          const ak = $("ana-kbd");
          if (ak) focusHidden(ak);
          renderHintPanel();
        }
      };
    });
    $("hint-clue").querySelectorAll("button.gw[data-aw]").forEach((b) => {
      b.onmousedown = keepFocus;
      b.onclick = () => {
        // The word comes from the clue itself, not read back out of the DOM.
        const cur = currentEntry();
        const t = cur && tokensOfClue(cur)[Number(b.getAttribute("data-aw"))];
        const w = t && t.text.replace(/[^A-Za-z]/g, "");
        if (w) toggleRingWord(b.getAttribute("data-aw"), w.toUpperCase());
      };
    });
    const shuffle = document.getElementById("ana-shuffle");
    // Struck letters survive a shuffle: they are the ones already on the grid,
    // and dealing again is a fresh look at what is LEFT.
    //
    // Surviving means staying WHERE THEY ARE, not merely staying crossed out:
    // a solver who has placed three letters must not watch their own three
    // answers scatter along with the question. Only the positions still in play
    // trade places — the unstruck ones that ringPins() does not hold at their
    // answer position.
    if (shuffle) shuffle.onmousedown = keepFocus;
    if (shuffle && ring) shuffle.onclick = () => {
      const prevRects = ringTileRects();
      const free = [];
      ring.order.forEach((idx, pos) => {
        if (!ring.struck[idx] && (ring.pins || {})[pos] === undefined) free.push(pos);
      });
      ring.order = dealRing(ring.letters, ring.forbidden, ring.order, free);
      renderHintPanel();
      playRingFlip(prevRects);
    };
    // Clicking the disc itself (not a tile) is how a mouse/touch user starts
    // typing: focus #ana-kbd — a real input, so it takes a hardware keyboard
    // directly and raises a soft one on a phone — then redraw so the focus
    // ring (ringKbdFocused() in ringHTML) appears immediately rather than on
    // whatever render happens to come next.
    const disc = panel.querySelector(".ana-disc");
    if (disc && ring) disc.onclick = () => {
      const ak = $("ana-kbd");
      if (ak) focusHidden(ak);
      renderHintPanel();
    };
  }

  // ---------- score ----------
  // What this clue costs. Frozen at the moment it was solved: rungs opened after
  // that are a solver studying a clue they already got, and charging for the
  // lesson would make the unlock in rungAvailable a trap. The group's cost is the
  // count when its LAST leg went in, and rungs only ever accumulate, so that is
  // the largest of the legs' snapshots.
  function hintsCharged(e) {
    // Rungs that were earned by naming the words don't count. They are on the
    // screen because the solver asked to see whether they were right, not
    // because they needed telling.
    if (!groupSolved(e)) return Math.max(0, shownRungs(e).length - earnedRungs(e).length);
    const key = entryKey(e);
    return frozenCharge(solvedWith, entries.filter((g) => entryKey(g) === key).map(entryId));
  }
  // Paper keeps Clear and Reset and swaps the three checks for "I'm done",
  // which is Check grid and the end of paper mode in one press. The switch
  // says whether this puzzle is on paper, and is gone where there is nothing
  // to hide.
  function drawPaperTools() {
    const on = paperHides();
    ["chk-label", "chk-letter", "chk-entry", "chk-grid"].forEach((id) => $(id).classList.toggle("hidden", on));
    $("paper-done").classList.toggle("hidden", !on);
    // After a verdict, a second button is the way to see where (and end paper).
    $("paper-reveal").classList.toggle("hidden", !(on && paperAsked()));
    $("paper-toggle").checked = on;
    $("paper-switch").classList.toggle("hidden", !on && !paperable());
  }
  // A solved clue's price given a save's solvedWith and the ids of its legs:
  // the largest leg's snapshot. Takes the map rather than reading the live one
  // so the stats page prices a clue in any save exactly as the scorebar prices
  // the one on screen.
  const frozenCharge = (sw, legIds) => legIds.reduce((n, id) => Math.max(n, sw[id] || 0), 0);
  // What "no hints" means, everywhere it is asked: no rung charged and no
  // letter revealed. The scorebar, the gold tint, the clue list's star and the
  // stats page all call this one, so none of them can drift from the others.
  const cleanSolve = (charged, reveals) => !charged && !(reveals > 0);

  function renderScore() {
    drawPaperTools();
    if (paperHides()) {
      $("scorebar").innerHTML = "Paper mode: no auto-check, nothing marked as you type. When you are done, press <strong>Is it right?</strong> to verify the whole grid.";
      drawScoreExtras();
      return;
    }
    const total = entries.filter((e) => !leaderOf[entryId(e)]).length;
    let solved = 0, noHints = 0, levelsUsed = 0, lettersRevealed = 0;
    const counted = {};
    entries.forEach((e) => {
      const key = entryKey(e);
      if (counted[key]) return;
      counted[key] = true;
      const rungs = hintsCharged(e);
      if (groupSolved(e)) {
        solved++;
        if (cleanSolve(rungs, revealsUsed[key])) noHints++;
      }
      levelsUsed += rungs;
      lettersRevealed += revealsUsed[key] || 0;
    });
    $("scorebar").innerHTML =
      `Solved <strong>${solved}/${total}</strong> clues · <strong>${noHints}</strong> with no hints · <strong>${levelsUsed}</strong> hints used`
      + (lettersRevealed ? ` · plus <strong>${lettersRevealed}</strong> letter${lettersRevealed > 1 ? "s" : ""} revealed` : "");
    drawScoreExtras();
  }

  // ---------- stats ----------
  // Everything on the stats panel is read off the saves (one ct:<id> per puzzle
  // started, merged across devices by sync/merge.js) and nothing is written: a
  // stored total is a second copy of what the saves already say, and two
  // devices would disagree about it. The score counts hints, never time, so no
  // figure here is a duration or a speed.
  //
  // A clue counts once every square of it is right in the save, the test the
  // scorebar makes live. It costs its charged rungs (frozenCharge) plus the
  // letters revealed on it, so a cost of 0 is exactly cleanSolve. When it was
  // solved is the latest letterAt stamp on its squares. Its types are its
  // annotation's, else the blog's: what annOf hands the ladder's type rung.
  //
  // Every clue of a loaded puzzle not yet solved is in `open`, the pool the
  // practice link picks from: a puzzle with no save is all open.
  function clueLedger() {
    const clues = [], open = [], totals = {};
    const saves = savedProgress();
    Object.keys(window.CRYPTIC_PUZZLES).forEach((id) => {
      const puz = window.CRYPTIC_PUZZLES[id];
      if (!puz || !puz.entries) return;
      const s = (fitsGrid(saves[id], puz) && saves[id]) || {}, letters = s.letters || {}, stamps = s.letterAt || {};
      const all = expandEntries(puz.entries).concat(offGridEntries(puz));
      const lead = buildLeaderOf(all);
      const legs = {};
      all.forEach((e) => {
        const key = lead[entryId(e)] || entryId(e);
        (legs[key] = legs[key] || []).push(e);
      });
      totals[id] = Object.keys(legs).length;
      // A puzzle on paper has solved nothing yet and offers no clue to
      // practise: its ladder is switched off.
      if (onPaper(id)) return;
      Object.keys(legs).forEach((key) => {
        let at = 0, solved = true;
        legs[key].forEach((e) => {
          if (e.offGrid) {
            const id = entryId(e);
            if (!e.solution || (letters[id] || "").replace("!", "") !== e.solution) solved = false;
            at = Math.max(at, stamps[id] || 0);
            return;
          }
          for (let i = 0; i < e.length; i++) {
            const sq = squareOf(e, i);
            if (!e.solution || !letters[sq] || letters[sq][0] !== e.solution[i]) solved = false;
            at = Math.max(at, stamps[sq] || 0);
          }
        });
        const head = legs[key].find((e) => entryId(e) === key) || legs[key][0];
        const types = ((head.annotation || head.blog || {}).type || []).filter((t) => TYPES[t]);
        if (!solved) {
          // A practice link opens on its clue, which a jigsaw cannot do.
          if (head.solution && types.length && !head.offGrid && !isJigsaw(BY_ID[id])) open.push({ id, ref: tag(head), types, started: !!saves[id] });
          return;
        }
        const hints = frozenCharge(s.solvedWith || {}, legs[key].map(entryId));
        const reveals = (s.revealsUsed || {})[key] || 0;
        const t = s.timing || {};
        clues.push({ id, key, at: at || t.solvedAt || t.lastAt || s.updated || 0, cost: hints + reveals, types,
                     clean: cleanSolve(hints, reveals) });
      });
    });
    clues.sort((a, b) => a.at - b.at);
    return { clues, open, totals };
  }

  // Ranks go on clean solves and on how few hints the recent ones took, never
  // on volume: a clue that needed hints moves nobody up. The share is of the
  // last RANK_WINDOW clues so the rank says how you solve now, and it can fall.
  // Computed on every draw and never stored.
  const RANK_WINDOW = 50;
  const RANKS = [
    { name: "Novice", clean: 0, low: 0 },
    { name: "Apprentice", clean: 5, low: 0 },
    { name: "Solver", clean: 25, low: 0.3 },
    { name: "Adept", clean: 75, low: 0.45 },
    { name: "Expert", clean: 200, low: 0.6 },
    { name: "Master", clean: 500, low: 0.75 },
    { name: "Setter", clean: 1000, low: 0.85 },
  ];
  // Each is reached on the one solve that first makes its test true, so the
  // walk below knows the date and the clue, and the solve can say so.
  // Milestones never run out: each kind climbs 1, 5, 10, 25, 50, 100, 250, …,
  // and the ladder is ordered by roughly how many clues each takes, a puzzle
  // being about 30 clues and a clean clue about two plain ones, so the next
  // three ahead are always within reach of each other.
  const MILESTONE_KINDS = [
    ["clues", 1, "clue solved", "clues solved", 100],
    ["clean", 1.5, "clue with no hints", "clues with no hints", 10],
    ["puzzles", 30, "puzzle finished", "puzzles finished", 5],
    ["cleanPuzzles", 60, "puzzle with no hints", "puzzles with no hints", 5],
  ];
  const MILESTONES = MILESTONE_KINDS.flatMap(([key, weight, one, many, from]) => {
    const steps = [1];
    for (let d = 1; d * weight <= 1e6; d *= 10) [d, 2.5 * d, 5 * d].forEach((k) => k >= from && k * weight <= 1e6 && steps.push(k));
    return steps.map((k) => ({ k, cost: k * weight, label: k === 1 ? `First ${one}` : `${k.toLocaleString("en")} ${many}`,
      test: (n) => n[key] >= k }));
  }).filter((m, i, all) => all.findIndex((o) => o.label === m.label) === i)
    .sort((a, b) => a.cost - b.cost).map((m) => [m.label, m.test]);
  const DAY_MS = 864e5;

  // A local calendar day, as a number that sorts: a streak is about the
  // solver's days, and a UTC day would split an evening in two.
  const dayNum = (d) => d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
  const dayBefore = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() - 1);
  // Consecutive local days with a puzzle finished on them (timing.solvedAt).
  // Today not finished yet still leaves yesterday's run alive.
  // `skip` leaves one puzzle out: the streak as it stood before that finish.
  function puzzleStreak(now, skip) {
    const days = {};
    const saves = savedProgress();
    Object.keys(saves).forEach((id) => {
      const t = id !== skip && saves[id].timing && saves[id].timing.solvedAt;
      if (t) days[dayNum(new Date(t))] = new Date(t);
    });
    let d = new Date(now), current = 0;
    if (!days[dayNum(d)]) d = dayBefore(d);
    while (days[dayNum(d)]) { current++; d = dayBefore(d); }
    let best = 0;
    Object.keys(days).forEach((k) => {
      if (days[dayNum(dayBefore(days[k]))]) return;
      let run = 0;
      for (let e = days[k]; days[dayNum(e)]; e = new Date(e.getFullYear(), e.getMonth(), e.getDate() + 1)) run++;
      best = Math.max(best, run);
    });
    return { current, best };
  }

  // The rank a list of solved clues earns, oldest first.
  function rankOf(clues) {
    const clean = clues.filter((c) => c.clean).length;
    const recent = clues.slice(-RANK_WINDOW);
    const low = recent.length ? recent.filter((c) => c.cost <= 1).length / recent.length : 0;
    let rank = 0;
    while (rank + 1 < RANKS.length && clean >= RANKS[rank + 1].clean && low >= RANKS[rank + 1].low) rank++;
    return { rank, low };
  }

  const perClue = (list) => list.reduce((n, c) => n + c.cost, 0) / list.length;
  const oneDp = (x) => (Math.round(x * 10) / 10).toFixed(1);

  function solverStats(now) {
    const { clues, open, totals } = clueLedger();
    const n = { clues: 0, clean: 0, puzzles: 0, cleanPuzzles: 0 };
    const got = {}, dirty = {}, finished = {};
    const milestones = MILESTONES.map(([label]) => ({ label, at: 0, id: null }));
    clues.forEach((c) => {
      n.clues++;
      if (c.clean) n.clean++; else dirty[c.id] = true;
      got[c.id] = (got[c.id] || 0) + 1;
      if (got[c.id] === totals[c.id]) {
        n.puzzles++;
        if (!dirty[c.id]) n.cleanPuzzles++;
        finished[c.id] = { at: c.at, clean: !dirty[c.id] };
      }
      MILESTONES.forEach(([, test], i) => {
        if (!milestones[i].id && test(n)) Object.assign(milestones[i], { at: c.at, id: c.id });
      });
    });
    const hist = [0, 0, 0, 0];
    clues.forEach((c) => { hist[Math.min(c.cost, 3)]++; });
    const { rank, low } = rankOf(clues);
    // Hints per clue for each of the last twelve weeks, oldest first; null for
    // a week with nothing solved, which the sparkline leaves as a gap.
    const weeks = [];
    for (let w = 11; w >= 0; w--) {
      const inWeek = clues.filter((c) => c.at <= now - w * 7 * DAY_MS && c.at > now - (w + 1) * 7 * DAY_MS);
      weeks.push(inWeek.length ? perClue(inWeek) : null);
    }
    const last30 = clues.filter((c) => c.at > now - 30 * DAY_MS);
    const prev30 = clues.filter((c) => c.at > now - 60 * DAY_MS && c.at <= now - 30 * DAY_MS);
    return { clues, open, finished, now, n, hist, low, rank, milestones, weeks, streak: puzzleStreak(now),
             trend: last30.length >= 5 && prev30.length >= 5 ? [perClue(prev30), perClue(last30)] : null };
  }

  // The panel is these sections in order, each a function of the one computed
  // solverStats. Another view of the same saves is another entry here.
  function statsSummaryHTML(st) {
    const solved = st.n.clues;
    const cell = (v, label) => `<div class="stat"><strong>${v}</strong><span>${label}</span></div>`;
    const bars = st.hist.map((count, i) => {
      const pct = st.hist.some(Boolean) ? Math.round(100 * count / Math.max(...st.hist)) : 0;
      return `<div class="hist-row${i ? "" : " clean"}"><span class="hist-label">${i === 3 ? "3+" : i}</span>`
        + `<span class="hist-bar" style="width:max(1.6em, ${pct}%)">${count}</span></div>`;
    }).join("");
    return `<div class="stat-row">${cell(st.n.puzzles, "puzzles finished")}${cell(solved, "clues solved")}`
      + cell(solved ? Math.round(100 * st.n.clean / solved) + "%" : "–", "with no hints")
      + cell(solved ? oneDp(perClue(st.clues)) : "–", "hints per clue") + `</div>`
      + `<h3 class="stats-h">Hints per clue</h3><div class="hist">${bars}</div>`
      + `<p class="muted small-note">A revealed letter counts as a hint, so 0 is a clue solved with no help at all.</p>`;
  }
  function statsTrendHTML(st) {
    const pts = st.weeks.map((v, i) => (v === null ? null : [i * 10, v]));
    const top = Math.max(3, ...st.weeks.filter((v) => v !== null));
    const y = (v) => (2 + 26 * (1 - v / top)).toFixed(1);
    // One polyline per unbroken run of weeks, so an empty week is a gap rather
    // than a line drawn through a week nobody solved in.
    const runs = [[]];
    pts.forEach((p) => { if (p) runs[runs.length - 1].push(p); else if (runs[runs.length - 1].length) runs.push([]); });
    const lines = runs.filter((r) => r.length).map((r) => r.length > 1
      ? `<polyline points="${r.map(([x, v]) => x + 2 + "," + y(v)).join(" ")}"/>`
      : `<circle cx="${r[0][0] + 2}" cy="${y(r[0][1])}" r="1.8"/>`).join("");
    let line = "Solve clues on a few different weeks and your trend shows up here.";
    if (st.trend) {
      const [a, b] = st.trend.map(oneDp);
      line = a === b ? `Your hints per clue held at ${b} over 30 days.`
        : `Your hints per clue ${+b < +a ? "fell" : "rose"} from ${a} to ${b} over 30 days.`;
    }
    return `<h3 class="stats-h">Trend</h3>`
      + `<svg class="spark" viewBox="0 0 114 30" role="img" aria-label="Hints per clue, week by week, for the last twelve weeks">`
      + `<line x1="0" y1="28" x2="114" y2="28"/>${lines}</svg>`
      + `<p class="stats-line">${line}</p>`
      + `<p class="muted small-note">Hints per clue each week for the last twelve weeks. Lower is better.</p>`;
  }
  function statsRankHTML(st) {
    const next = RANKS[st.rank + 1];
    let need = "The top rank. Every clue from here is for the love of it.";
    if (next) {
      const more = next.clean - st.n.clean;
      const wants = [];
      if (more > 0) wants.push(`${more} more clue${more > 1 ? "s" : ""} with no hints`);
      if (st.low < next.low) wants.push(`${Math.round(next.low * 100)}% of your last ${RANK_WINDOW} clues on one hint or none (now ${Math.round(st.low * 100)}%)`);
      need = `Next, ${next.name}: ${wants.join(", and ")}.`;
    }
    return `<h3 class="stats-h">Rank</h3><p class="rank"><strong>${RANKS[st.rank].name}</strong></p>`
      + `<p class="stats-line">${need}</p>`;
  }
  function statsStreakHTML(st) {
    const days = (k) => `${k} day${k === 1 ? "" : "s"}`;
    return `<h3 class="stats-h">Streak</h3><p class="stats-line"><strong>${days(st.streak.current)}</strong> in a row with a puzzle finished`
      + ` · best ${days(st.streak.best)}</p>`;
  }
  function statsMilestonesHTML(st) {
    // 0 is a save from before letters were stamped: the day is unknown, not 1970.
    const when = (t) => t ? localDay(new Date(t)) : "";
    // The journey, not the map: the last few reached and the next two ahead.
    const reached = st.milestones.filter((m) => m.id).sort((a, b) => a.at - b.at).slice(-3);
    const ahead = st.milestones.filter((m) => !m.id).slice(0, 2);
    return `<h3 class="stats-h">Milestones</h3><ul class="milestones">`
      + reached.map((m) => `<li class="reached">${m.label}<span class="muted">${when(m.at)}</span></li>`).join("")
      + ahead.map((m) => `<li class="ahead">${m.label}</li>`).join("") + `</ul>`;
  }
  // Per clue type: the share of its solved clues that cost nothing, and hints
  // per clue. A compound clue counts for each type it is. Only a type with
  // TYPE_MIN solved clues is ranked, since three clues say nothing about a skill.
  // The weakest ranked type, lowest clean share and then most hints, gets a
  // link to an unsolved clue of it in a loaded puzzle, one already started if
  // there is one: the ?c= deep link a shared clue uses.
  const TYPE_MIN = 5;
  function statsTypesHTML(st) {
    const by = {};
    st.clues.forEach((c) => c.types.forEach((t) => (by[t] = by[t] || []).push(c)));
    const rows = Object.keys(by).map((t) => {
      const clean = by[t].filter((c) => c.clean).length;
      return { t, list: by[t], clean, share: clean / by[t].length };
    });
    if (!rows.length) return "";
    const ranked = rows.filter((r) => r.list.length >= TYPE_MIN)
      .sort((a, b) => b.share - a.share || perClue(a.list) - perClue(b.list));
    const few = rows.filter((r) => r.list.length < TYPE_MIN).sort((a, b) => b.list.length - a.list.length);
    const weakest = ranked.length > 1 ? ranked[ranked.length - 1] : null;
    const row = (r) => {
      // 100 * clean / n, not 100 * share: 23/40 is 0.575, and 100 * 0.575 is
      // 57.49999… in floating point, so it would round down to 57%.
      const pct = Math.round(100 * r.clean / r.list.length), rankable = r.list.length >= TYPE_MIN;
      return `<div class="type-row${rankable ? "" : " few"}${r === weakest ? " weakest" : ""}">`
        + `<span class="type-label">${esc(TYPES[r.t].label)}</span>`
        + `<span class="type-track"><span class="type-fill" style="width:${rankable ? pct : 0}%"></span></span>`
        + `<span class="type-num">${rankable ? pct + "%" : "–"} · ${oneDp(perClue(r.list))}</span>`
        + `<span class="type-n muted">${r.list.length}</span></div>`;
    };
    let practise = "";
    if (weakest) {
      const pool = st.open.filter((o) => o.types.includes(weakest.t));
      const pick = pool.find((o) => o.started) || pool[0];
      practise = pick
        ? `<p class="stats-line"><a class="practise" href="${at(`?p=${encodeURIComponent(pick.id)}&c=${pick.ref}`)}">`
          + `Practise your weakest: ${esc(TYPES[weakest.t].label.toLowerCase())}</a></p>` : "";
    }
    return `<h3 class="stats-h">By clue type</h3><div class="types">${ranked.concat(few).map(row).join("")}</div>`
      + practise
      + `<p class="muted small-note">Share solved with no hints, then hints per clue, then clues solved. `
      + `A type is ranked from ${TYPE_MIN} clues.</p>`;
  }

  // Puzzles finished in each series with a save in it, most first; bars are
  // scaled to the top series, never to the archive size.
  function statsShelfHTML(st) {
    const done = {}, touched = {};
    Object.keys(savedProgress()).forEach((id) => { if (BY_ID[id]) touched[BY_ID[id].series] = true; });
    Object.keys(st.finished).forEach((id) => { if (BY_ID[id]) done[BY_ID[id].series] = (done[BY_ID[id].series] || 0) + 1; });
    const list = Object.keys(touched).filter((s) => SERIES_BADGE[s])
      .sort((a, b) => (done[b] || 0) - (done[a] || 0) || a.localeCompare(b));
    if (!list.length) return "";
    const top = Math.max(1, ...list.map((s) => done[s] || 0));
    return `<h3 class="stats-h">Finished by series</h3><div class="shelf">` + list.map((s) => {
      const k = done[s] || 0;
      return `<div class="shelf-row">${seriesChip(s)}<span class="type-track"><span class="type-fill" `
        + `style="width:${k ? `${(100 * k / top).toFixed(1)}%` : 0}"></span></span>`
        + `<span class="shelf-n">${k.toLocaleString()}</span></div>`;
    }).join("") + `</div>`;
  }

  // The last 52 weeks, a column a week from Sunday, today in the last column.
  // A day's shade is the clues solved on it and a ring marks a puzzle finished
  // with no hints. Local days, as the streak counts them.
  function statsYearHTML(st) {
    const count = {}, clean = {};
    st.clues.forEach((c) => { const k = dayNum(new Date(c.at)); count[k] = (count[k] || 0) + 1; });
    Object.keys(st.finished).forEach((id) => { if (st.finished[id].clean) clean[dayNum(new Date(st.finished[id].at))] = true; });
    const today = new Date(st.now);
    const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - today.getDay() - 51 * 7);
    const level = (k) => (!k ? 0 : k < 5 ? 1 : k < 15 ? 2 : k < 30 ? 3 : 4);
    const fmt = localDay;
    let cells = "";
    for (let i = 0; ; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      if (d > today) break;
      const k = dayNum(d), c = count[k] || 0;
      cells += `<rect x="${Math.floor(i / 7) * 11}" y="${(i % 7) * 11}" width="9" height="9" rx="1.5" `
        + `class="l${level(c)}${clean[k] ? " clean" : ""}"><title>${fmt(d)}: ${c} clue${c === 1 ? "" : "s"}`
        + `${clean[k] ? ", a puzzle with no hints" : ""}</title></rect>`;
    }
    return `<h3 class="stats-h">Year</h3>`
      + `<svg class="year" viewBox="0 0 571 76" role="img" aria-label="Clues solved each day for the last 52 weeks">${cells}</svg>`
      + `<p class="muted small-note">Darker is more clues solved that day. A ring is a puzzle finished with no hints.</p>`;
  }
  const STATS_SECTIONS = [statsSummaryHTML, statsTrendHTML, statsRankHTML, statsStreakHTML, statsTypesHTML,
                          statsYearHTML, statsShelfHTML, statsMilestonesHTML];

  // Every started puzzle's file, then `then` once: the ledger needs each
  // puzzle's answers, and a sync pull can bring saves for files never fetched.
  // With `fresh`, the newest annotated puzzle not started too, so the practice
  // link has unsolved clues to pick from when everything started is finished.
  function whenStartedLoaded(then, fresh) {
    const saves = savedProgress();
    const ids = Object.keys(saves).filter((id) => BY_ID[id]);
    const unstarted = fresh && INDEX.puzzles.find((p) => p.annotated && p.hasSolutions && !saves[p.id]);
    if (unstarted) ids.push(unstarted.id);
    let left = ids.length + 1;
    const one = () => { if (--left === 0) then(); };
    ids.forEach((id) => loadPuzzle(id, one));
    one();
  }
  function renderStats() {
    const st = solverStats(Date.now());
    setHTML($("stats-body"), STATS_SECTIONS.map((f) => f(st)).join(""));
  }
  // Both toggles return whether the panel ended up open, so a click that
  // opened it can be counted and one that closed it is not.
  function toggleStats(show) {
    const open = toggleStatsPanel(show);
    syncRoute();
    return open;
  }
  function toggleStatsPanel(show) {
    if (!showPanel("stats-panel", show)) return false;
    if (P) flushState();
    whenStartedLoaded(() => { if (!$("stats-panel").classList.contains("hidden")) renderStats(); }, true);
    return true;
  }

  // What the letter just typed earned, each announced by a toast linking to
  // the stats. Nothing records what was announced: an achievement is this
  // solve's when the clue that reached it carries this save's own stamp, so
  // everything earned before (on this device, another one, or before toasts
  // existed) stays quiet, and a sync merge, which types nothing, never toasts.
  // The save is written first so the solve is in it. A paper end-check passes
  // `any`: the ledger left the whole puzzle out until then, so all of it is
  // this check's, whatever its letters' stamps say.
  const STREAK_STEPS = [3, 7, 14, 30, 50, 100, 200, 365, 500, 1000];
  function noteMilestone(any) {
    clearTimeout(saveTimer);
    writeState();
    const id = P.id, stamp = (store.get(stateKey(), null) || {}).updated;
    whenStartedLoaded(() => {
      if (!P || P.id !== id) return;
      achievementsReached(Date.now(), id, (at) => any || at === stamp).forEach(toastAchievement);
    });
  }
  function achievementsReached(now, id, mine) {
    const st = solverStats(now);
    const got = st.milestones.filter((m) => m.id === id && mine(m.at)).map((m) => m.label);
    if (st.rank > rankOf(st.clues.filter((c) => !(c.id === id && mine(c.at)))).rank) got.push(`Rank: ${RANKS[st.rank].name}`);
    const k = st.streak.current;
    if (st.finished[id] && mine(st.finished[id].at) && STREAK_STEPS.includes(k) && puzzleStreak(now, id).current < k) {
      got.push(`${k}-day streak`);
    }
    return got;
  }
  function drawScoreExtras() {
    const k = puzzleStreak(Date.now()).current;
    setHTML($("streak"), k ? `<strong>${k}</strong>-day streak` : "");
  }

  // A toast per achievement, stacked in #toasts: the whole toast opens the
  // stats panel, the ✕ only closes it, and either way it goes by itself after
  // TOAST_MS. Each one sets off a small burst where it lands.
  const TOAST_MS = 6000;
  function toastAchievement(label) {
    const box = $("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.innerHTML = `<a class="toast-link" href="#stats"><span aria-hidden="true">🏆</span> `
      + `<strong>${esc(label)}</strong> <span class="toast-go">— see your stats</span></a>`
      + `<button class="toast-x ghost small" aria-label="Dismiss">✕</button>`;
    const drop = () => { clearTimeout(timer); if (el.remove) el.remove(); };
    el.onclick = (ev) => {
      if (ev && ev.preventDefault) ev.preventDefault();
      const close = ev && ev.target && ev.target.classList && ev.target.classList.contains("toast-x");
      if (!close && toggleStats(true)) beacon("stats");
      drop();
    };
    const timer = setTimeout(drop, TOAST_MS);
    box.appendChild(el);
    fireworksAt(el, 2, 36);
  }

  // ---------- fireworks ----------
  // One canvas over the whole page, made on the first burst and drawn only
  // while something is in the air. A spark's position is a closed form of its
  // age (launch, drag, gravity), so a frame is a loop over an array and a
  // dropped frame costs nothing but a frame. Nothing at all under
  // prefers-reduced-motion.
  const FW_GRAVITY = 90, FW_DRAG = 1.6;
  let fw = null;
  function fireworks(shells) {
    if (reduceMotion() || !document.body || typeof requestAnimationFrame !== "function") return;
    if (!fw) {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext && canvas.getContext("2d");
      if (!ctx) return;
      canvas.className = "fw-canvas";
      canvas.setAttribute("aria-hidden", "true");
      document.body.appendChild(canvas);
      fw = { canvas, ctx, parts: [], running: false };
    }
    const css = getComputedStyle(document.documentElement);
    const colors = ["--burst-1", "--burst-2", "--burst-3"].map((v) => css.getPropertyValue(v).trim())
      .filter(Boolean).concat(["#f5b82e", "#ff7a59"]);
    const t0 = performance.now();
    shells.forEach((sh, n) => {
      const color = colors[n % colors.length], alt = colors[(n + 2) % colors.length];
      const born = t0 + (sh.delay || 0) * 1000;
      if (sh.rocket) {
        fw.parts.push({ rocket: true, x: sh.x, y0: window.innerHeight, y: sh.y, born: born - 550, life: 550, color });
      }
      const sparks = sh.sparks || 40, speed = sh.speed || 220;
      for (let i = 0; i < sparks; i++) {
        const a = (i / sparks) * Math.PI * 2 + Math.random() * 0.2;
        const v = speed * (0.55 + Math.random() * 0.45);
        fw.parts.push({ x: sh.x, y: sh.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, born,
                        life: 900 + Math.random() * 700, color: i % 4 ? color : alt, size: 1.8 + Math.random() * 1.6 });
      }
    });
    if (!fw.running) { fw.running = true; requestAnimationFrame(fwFrame); }
  }
  function fwAt(p, s) {
    const k = (1 - Math.exp(-FW_DRAG * s)) / FW_DRAG;
    return [p.x + p.vx * k, p.y + p.vy * k + 0.5 * FW_GRAVITY * s * s];
  }
  function fwFrame(t) {
    const { canvas, ctx } = fw;
    const dpr = window.devicePixelRatio || 1, w = window.innerWidth, h = window.innerHeight;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    fw.parts = fw.parts.filter((p) => t < p.born + p.life);
    fw.parts.forEach((p) => {
      if (t < p.born) return;
      const f = (t - p.born) / p.life;
      ctx.globalAlpha = p.rocket ? 1 : Math.min(1, 2.2 * (1 - f));
      ctx.fillStyle = ctx.strokeStyle = p.color;
      if (p.rocket) {
        const e = 1 - (1 - f) * (1 - f), y = p.y0 + (p.y - p.y0) * e;
        ctx.beginPath(); ctx.arc(p.x, y, 2.2, 0, Math.PI * 2); ctx.fill();
        ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(p.x, y); ctx.lineTo(p.x, y + 26); ctx.stroke();
        return;
      }
      const s = (t - p.born) / 1000;
      const [x, y] = fwAt(p, s), [px, py] = fwAt(p, Math.max(0, s - 0.08));
      ctx.lineWidth = p.size; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, p.size, 0, Math.PI * 2); ctx.fill();
    });
    ctx.globalAlpha = 1;
    if (fw.parts.length) requestAnimationFrame(fwFrame);
    else { ctx.clearRect(0, 0, w, h); fw.running = false; }
  }
  // `shells` small bursts centred on an element, staggered by a beat.
  function fireworksAt(el, shells, sparks) {
    if (!el || !el.getBoundingClientRect || reduceMotion()) return;
    const r = el.getBoundingClientRect();
    fireworks(Array.from({ length: shells }, (_, i) => ({
      x: r.left + r.width * (shells > 1 ? (i + 0.5) / shells : 0.5), y: r.top + r.height / 2,
      sparks, speed: shells > 1 ? 280 : 200, delay: i * 0.18,
    })));
  }
  // The finish: rockets up the screen and bursts across it. A grid finished
  // without a single hint gets twice the show.
  function finishFireworks(clean) {
    const shells = clean ? 16 : 8, w = window.innerWidth || 0, h = window.innerHeight || 0;
    fireworks(Array.from({ length: shells }, (_, i) => ({
      x: w * (0.12 + 0.76 * ((i * 0.618) % 1)), y: h * (0.15 + 0.3 * ((i * 0.382) % 1)),
      sparks: clean ? 70 : 50, speed: clean ? 300 : 250, delay: i * (clean ? 0.28 : 0.35), rocket: true,
    })));
  }

