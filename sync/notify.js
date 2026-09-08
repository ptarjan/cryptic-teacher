/* The two decisions the push fan-out makes before it encrypts anything: what a
   notification is CALLED, and whether this subscriber wants to be woken yet.

   Both are pure — a puzzle and a table in, a string out; a clock and a zone in,
   a yes or no out — and both are wrong in ways nobody would ever see. A title
   that does not name the paper reads as somebody else's crossword. A hold that
   is off by a zone wakes a phone at four in the morning, which is exactly the
   thing it was added to stop. So they live here rather than inside
   sync/worker.js's fan-out loop, where the only way to check them would be to
   send a real push at a real phone.

   Loaded by the Worker with `import` and by tools/smoke_test.js with
   `require`, hence the UMD wrapper — the same arrangement, for the same
   reason, as sync/merge.js. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CTNotify = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /* What the notification is called.

     A puzzle's `name` is the paper's own — "Cryptic crossword No 30,106",
     "Quiptic crossword No 1,398", "Everyman crossword No 4,168" — and not one
     of those says whose crossword it is. On the site that is fine: the row
     wears a badge next to it. On a lock screen there is no badge, only the
     title, and the Guardian's three series arrive anonymous.

     The paper comes from `papers` in puzzles/index.json, which the fan-out has
     already fetched, and which is written out of tools/series.py at reindex
     time. That is deliberately NOT a table here: a second list of papers in the
     Worker is the list that would still say five the night a sixth arrives.

     A name that already opens with its paper is left alone, which is what keeps
     the Independent's two series from reading "Independent Independent". */
  function title(puzzle, papers) {
    const name = String((puzzle && puzzle.name) || "");
    const paper = String((papers && puzzle && papers[puzzle.series]) || "");
    if (!paper || name === paper || name.startsWith(paper + " ")) return name;
    return paper + " " + name;
  }

  /* "07:00" as minutes past local midnight, or null if it is not a time.

     null means the subscriber asked for no hold, and every caller treats it
     that way — an unparseable time must never become a hold nobody chose. */
  function parseAfter(value) {
    const m = typeof value === "string" && /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value);
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }

  /* The local clock in an IANA zone, as minutes past midnight; null if the zone
     is not one Intl knows.

     h23 rather than hour12:false, which some engines answer with "24" at
     midnight. formatToParts rather than a string, so nothing here has to parse
     a locale's punctuation. */
  function minutesOfDay(zone, now) {
    try {
      const parts = new Intl.DateTimeFormat("en-GB", {
        timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      }).formatToParts(new Date(now));
      const at = (type) => Number((parts.find((p) => p.type === type) || {}).value);
      const h = at("hour"), m = at("minute");
      if (!isFinite(h) || !isFinite(m)) return null;
      return h * 60 + m;
    } catch (e) {
      return null;   // RangeError: a zone string the runtime does not have
    }
  }

  /* The zone as it will be stored, or "" for one that cannot be used.

     Checked by ASKING Intl rather than against a list of 400-odd names: the
     shape test only keeps a hostile string out of the formatter, and the
     formatter itself is the authority on whether "America/Edmonton" exists. */
  function zone(value) {
    if (typeof value !== "string" || !/^[A-Za-z][A-Za-z0-9_+\-/]{1,63}$/.test(value)) return "";
    return minutesOfDay(value, Date.now()) === null ? "" : value;
  }

  /* May this subscriber be woken now?

     `after` is the earliest minute of the local day they said yes to, so this
     is a floor and not a window: 07:00 holds a puzzle annotated at 03:00 until
     the morning, and does nothing at all to one annotated at half past eleven
     at night.

     Every uncertainty resolves to TRUE — no time chosen, a zone this runtime
     does not know, a subscription written before any of this existed. Holding
     is the unusual behaviour and has to be asked for explicitly; the failure
     mode of guessing wrong the other way is a notification that never comes and
     never explains itself. */
  function due(after, zoneName, now) {
    if (!Number.isInteger(after) || after <= 0) return true;
    const mins = minutesOfDay(zoneName, now);
    if (mins === null) return true;
    return mins >= after;
  }

  return { title, parseAfter, minutesOfDay, zone, due };
});
