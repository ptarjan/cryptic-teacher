/* A QR code, generated here in the page.

   The thing being encoded is the sync code, and the sync code IS the account
   (sync/worker.js): posting it to an image service to be drawn would hand that
   service every grid on it. So the encoder is ~200 lines of arithmetic rather
   than an <img src> pointing at somebody else's server, and it ships as a
   separate file because index.html loads it only where a QR is actually shown.

   Byte mode, error level M, versions 1-10. The payload is one join URL and can
   never grow into a photograph, so the 30-version tail of the standard is
   capacity nobody here will ask for. encode() throws past the top version
   instead of silently drawing something a phone cannot read.

   Loaded as a plain <script> in the page; the UMD wrapper is what lets
   tools/qr_check.js run the same file against a reference encoder. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CTQR = factory();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* Level M, per version: [total codewords, EC codewords per block, blocks].
     Data codewords, and the split into short and long blocks, are derived from
     these three - a fourth column would be a second copy of the same fact, free
     to disagree with the first. */
  const VERSIONS = [
    [26, 10, 1], [44, 16, 1], [70, 26, 1], [100, 18, 2], [134, 24, 2],
    [172, 16, 4], [196, 18, 4], [242, 22, 4], [292, 22, 5], [346, 26, 5],
  ];
  // Alignment pattern centres, per version. Version 1 has none.
  const ALIGN = [
    [], [6, 18], [6, 22], [6, 26], [6, 30],
    [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
  ];
  // Bits left over after the last codeword, per version.
  const REMAINDER = [0, 7, 7, 7, 7, 7, 0, 0, 0, 0];

  // ---------- GF(256), the field the Reed-Solomon parity lives in ----------
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  for (let i = 0, x = 1; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d; // the primitive polynomial the standard names
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);

  /* The generator polynomial for n parity codewords: (x-a^0)...(x-a^(n-1)),
     highest power first, which is the order parity() divides by. */
  function generator(n) {
    let poly = [1];
    for (let i = 0; i < n; i++) {
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];                    // times x
        next[j + 1] ^= mul(poly[j], EXP[i]);   // times a^i
      }
      poly = next;
    }
    return poly;
  }

  function parity(data, n) {
    const gen = generator(n);
    const rem = new Uint8Array(data.length + n);
    rem.set(data);
    for (let i = 0; i < data.length; i++) {
      const lead = rem[i];
      if (!lead) continue;
      for (let j = 0; j < gen.length; j++) rem[i + j] ^= mul(gen[j], lead);
    }
    return rem.slice(data.length);
  }

  // BCH check bits, used for both the format and the version blocks. The
  // standard gives these as lookup tables; computing them is shorter than
  // transcribing 32 rows correctly.
  function bch(value, poly, bits) {
    let v = value << bits;
    const top = 1 << (bits + polyDegree(poly));
    for (let mask = top; mask > (1 << bits) - 1; mask >>= 1) {
      if (v & mask) v ^= poly * (mask / (1 << polyDegree(poly)));
    }
    return v;
  }
  function polyDegree(poly) {
    let d = -1;
    for (let p = poly; p; p >>= 1) d++;
    return d;
  }

  // ---------- the bitstream ----------
  function bytesOf(text) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(text);
    const out = [];
    for (const ch of unescape(encodeURIComponent(text))) out.push(ch.charCodeAt(0));
    return Uint8Array.from(out);
  }

  function codewords(data, version) {
    const [total, ecPerBlock, blocks] = VERSIONS[version - 1];
    const dataTotal = total - ecPerBlock * blocks;
    const bits = [];
    const push = (value, n) => { for (let i = n - 1; i >= 0; i--) bits.push((value >> i) & 1); };
    push(4, 4);                                   // byte mode
    push(data.length, version < 10 ? 8 : 16);     // the count field widens at 10
    for (const b of data) push(b, 8);
    for (let i = 0; i < 4 && bits.length < dataTotal * 8; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const out = new Uint8Array(dataTotal);
    for (let i = 0; i < bits.length; i++) out[i >> 3] |= bits[i] << (7 - (i % 8));
    // The standard's two pad codewords, alternating, for the rest.
    for (let i = bits.length / 8; i < dataTotal; i++) out[i] = (i - bits.length / 8) % 2 ? 0x11 : 0xec;
    return out;
  }

  /* Blocks are interleaved codeword by codeword so that a thumb over one corner
     damages a little of every block rather than all of one. */
  function interleave(all, version) {
    const [total, ecPerBlock, blocks] = VERSIONS[version - 1];
    const dataTotal = total - ecPerBlock * blocks;
    const longBlocks = dataTotal % blocks;
    const shortLen = Math.floor(dataTotal / blocks);
    const dataBlocks = [];
    const ecBlocks = [];
    for (let i = 0, at = 0; i < blocks; i++) {
      const len = shortLen + (i >= blocks - longBlocks ? 1 : 0);
      const block = all.slice(at, at + len);
      at += len;
      dataBlocks.push(block);
      ecBlocks.push(parity(block, ecPerBlock));
    }
    const out = [];
    for (let i = 0; i <= shortLen; i++) {
      for (const b of dataBlocks) if (i < b.length) out.push(b[i]);
    }
    for (let i = 0; i < ecPerBlock; i++) for (const b of ecBlocks) out.push(b[i]);
    return out;
  }

  // ---------- the grid ----------
  function blank(size) {
    const m = [];
    for (let r = 0; r < size; r++) m.push(new Int8Array(size).fill(-1)); // -1: still free
    return m;
  }

  function functionPatterns(m, version) {
    const size = m.length;
    const square = (top, left) => {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          const y = top + r, x = left + c;
          if (y < 0 || x < 0 || y >= size || x >= size) continue;
          const ring = r >= 0 && r <= 6 && c >= 0 && c <= 6 &&
            (r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4));
          m[y][x] = ring ? 1 : 0;
        }
      }
    };
    square(0, 0); square(0, size - 7); square(size - 7, 0);
    for (let i = 8; i < size - 8; i++) {
      const on = i % 2 === 0 ? 1 : 0;
      m[6][i] = on;
      m[i][6] = on;
    }
    const centres = ALIGN[version - 1];
    const last = centres[centres.length - 1];
    for (const cy of centres) {
      for (const cx of centres) {
        // Three corners belong to the finders; the fourth, and every centre
        // that lands on a timing pattern, is drawn.
        if ((cy === 6 || cy === last) && (cx === 6 || cx === last) &&
            !(cy === last && cx === last)) continue;
        for (let r = -2; r <= 2; r++) {
          for (let c = -2; c <= 2; c++) {
            m[cy + r][cx + c] = (Math.abs(r) === 2 || Math.abs(c) === 2 || (!r && !c)) ? 1 : 0;
          }
        }
      }
    }
    m[size - 8][8] = 1; // the module that is always dark
    // Format and version areas are reserved now and filled once the mask is
    // chosen; 0 keeps them out of the way of the zigzag.
    for (let i = 0; i < 9; i++) {
      if (m[8][i] === -1) m[8][i] = 0;
      if (m[i][8] === -1) m[i][8] = 0;
    }
    for (let i = 0; i < 8; i++) {
      if (m[8][size - 1 - i] === -1) m[8][size - 1 - i] = 0;
      if (m[size - 1 - i][8] === -1) m[size - 1 - i][8] = 0;
    }
    if (version >= 7) {
      const info = (version << 12) | bch(version, 0x1f25, 12);
      for (let i = 0; i < 18; i++) {
        const bit = (info >> i) & 1;
        m[Math.floor(i / 3)][size - 11 + (i % 3)] = bit;
        m[size - 11 + (i % 3)][Math.floor(i / 3)] = bit;
      }
    }
  }

  // Two modules wide, bottom-right upwards, snaking. Column 6 is the vertical
  // timing pattern and is stepped over rather than written round.
  function place(m, stream, version) {
    const size = m.length;
    let bit = 0;
    const next = () => {
      const byte = stream[bit >> 3];
      const on = byte === undefined ? 0 : (byte >> (7 - (bit % 8))) & 1;
      bit++;
      return on;
    };
    for (let right = size - 1; right > 0; right -= 2) {
      if (right === 6) right = 5;
      for (let step = 0; step < size; step++) {
        const up = ((size - 1 - right) & 2) === 0;
        const r = up ? size - 1 - step : step;
        for (const c of [right, right - 1]) if (m[r][c] === -1) m[r][c] = next();
      }
    }
    void version;
  }

  const MASKS = [
    (r, c) => (r + c) % 2 === 0,
    (r) => r % 2 === 0,
    (r, c) => c % 3 === 0,
    (r, c) => (r + c) % 3 === 0,
    (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
    (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
    (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
    (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
  ];

  // The standard's four penalties. Lowest total wins; the choice is not part of
  // decoding, but a badly masked code is one a phone gives up on.
  function penalty(m) {
    const size = m.length;
    let score = 0;
    let dark = 0;
    const runs = (get) => {
      for (let a = 0; a < size; a++) {
        let run = 1;
        const line = [];
        for (let b = 0; b < size; b++) {
          line.push(get(a, b));
          if (b && line[b] === line[b - 1]) run++;
          else run = 1;
          if (run === 5) score += 3;
          else if (run > 5) score += 1;
        }
        const s = line.join("");
        for (const pat of ["1011101" + "0000", "0000" + "1011101"]) {
          let at = s.indexOf(pat);
          while (at !== -1) { score += 40; at = s.indexOf(pat, at + 1); }
        }
      }
    };
    runs((a, b) => m[a][b]);
    runs((a, b) => m[b][a]);
    for (let r = 0; r < size - 1; r++) {
      for (let c = 0; c < size - 1; c++) {
        const v = m[r][c];
        if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) score += 3;
      }
    }
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) dark += m[r][c];
    score += Math.floor(Math.abs((dark * 100) / (size * size) - 50) / 5) * 10;
    return score;
  }

  function writeFormat(m, mask) {
    const size = m.length;
    // 00 is level M; the XOR stops an all-zero format from reading as valid.
    const bits = (((0 << 3) | mask) << 10 | bch((0 << 3) | mask, 0x537, 10)) ^ 0x5412;
    const at = (i) => (bits >> i) & 1;
    for (let i = 0; i <= 5; i++) m[i][8] = at(i);
    m[7][8] = at(6);
    m[8][8] = at(7);
    m[8][7] = at(8);
    for (let i = 9; i <= 14; i++) m[8][14 - i] = at(i);
    for (let i = 0; i <= 7; i++) m[8][size - 1 - i] = at(i);
    for (let i = 8; i <= 14; i++) m[size - 15 + i][8] = at(i);
  }

  /* The finished modules for `text`, as an array of rows of 0/1, with no quiet
     zone - the caller draws that, because how much white it can spare is a
     question about the panel and not about the code. */
  function encode(text) {
    const data = bytesOf(text);
    let version = 0;
    for (let v = 1; v <= VERSIONS.length; v++) {
      const [total, ec, blocks] = VERSIONS[v - 1];
      const capacity = total - ec * blocks - (v < 10 ? 2 : 3);
      if (data.length <= capacity) { version = v; break; }
    }
    if (!version) throw new Error("QR payload too long: " + data.length + " bytes");

    const stream = interleave(codewords(data, version), version);
    const size = version * 4 + 17;
    const base = blank(size);
    functionPatterns(base, version);
    const free = base.map((row) => Array.from(row, (v) => v === -1));
    place(base, stream, version);
    for (let i = 0; i < REMAINDER[version - 1]; i++) void i; // remainder bits are 0

    let best = null;
    for (let mask = 0; mask < 8; mask++) {
      const m = base.map((row) => Array.from(row));
      for (let r = 0; r < size; r++) {
        for (let c = 0; c < size; c++) if (free[r][c] && MASKS[mask](r, c)) m[r][c] ^= 1;
      }
      writeFormat(m, mask);
      const score = penalty(m);
      if (!best || score < best.score) best = { score, m };
    }
    return best.m;
  }

  return { encode };
}));
