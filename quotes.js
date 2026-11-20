/* Clue text is stored with straight quotes (tools/quotes.py); this curls them
   for display.

   ' after a letter or digit is an apostrophe or a closing quote: ’ either way.
   ' or " at the start, or after a space, a bracket, a dash, a slash or an
   opening quote, opens: ‘ “. The exception is a leading elision ('tis, 'em,
   'n', '90s), which is an apostrophe: ’. Anything else closes.

   One character for one, so every offset into the clue still points at the
   same letter. Loaded as a plain <script> in the page and required by the
   tests, hence the UMD wrapper. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CTQuotes = factory();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const OPENS_AFTER = /[\s([{—–\-/‘“]/;
  const ELISION = /^(?:tis|twas|twere|twill|twould|em|n|til|cause|neath|bout|gainst|nuff|ere|\d\d?s?)(?![A-Za-z])/i;

  function curl(text) {
    const s = String(text);
    if (s.indexOf("'") < 0 && s.indexOf('"') < 0) return s;
    let out = "";
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (c !== "'" && c !== '"') { out += c; continue; }
      const prev = i ? out[i - 1] : "";
      const opens = !prev || OPENS_AFTER.test(prev);
      if (c === '"') out += opens ? "“" : "”";
      else if (!opens || ELISION.test(s.slice(i + 1))) out += "’";
      else out += "‘";
    }
    return out;
  }

  return { curl };
}));
